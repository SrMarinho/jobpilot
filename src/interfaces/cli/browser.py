import os
import time
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from src.config.settings import logger
import src.config.settings as setting
from src.interfaces.cli.persistence import BOT_PROFILE_DIR

_stealth = Stealth()

_LAUNCH_TIMEOUT_MS = 90_000
_LAUNCH_RETRIES = 2
_RETRY_WAIT_S = 5
_LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")
_LOCK_FRESH_THRESHOLD_S = 60  # locks newer than this likely belong to a live Chrome


def _lock_is_fresh(lock_path: Path) -> bool:
    """True if the lock was touched recently — assume another live Chrome owns it."""
    try:
        age = time.time() - lock_path.stat().st_mtime
        return age < _LOCK_FRESH_THRESHOLD_S
    except Exception:
        return False


def _another_instance_active() -> bool:
    """Detect if another JobPilot instance is currently using the bot_profile."""
    profile = Path(BOT_PROFILE_DIR)
    if not profile.exists():
        return False
    for name in _LOCK_FILES:
        lock = profile / name
        if (lock.exists() or lock.is_symlink()) and _lock_is_fresh(lock):
            return True
    return False


def _clear_chrome_locks() -> None:
    """Remove ORPHAN Chrome singleton lock files from a previous crashed run.

    Skips fresh locks (< 60s old) to avoid stealing the lock from a parallel
    JobPilot instance (e.g. connect running while apply is also active).
    Without this guard, the second instance would silently kill the first.
    """
    profile = Path(BOT_PROFILE_DIR)
    if not profile.exists():
        return
    for name in _LOCK_FILES:
        lock = profile / name
        try:
            if not (lock.exists() or lock.is_symlink()):
                continue
            if _lock_is_fresh(lock):
                logger.info(
                    f"Skipping fresh Chrome lock ({name}) — another instance likely active"
                )
                continue
            lock.unlink()
            logger.info(f"Removed stale Chrome lock: {name}")
        except Exception as e:
            logger.warning(f"Could not remove {name}: {e}")


LOGIN_URLS = {
    "linkedin": "https://www.linkedin.com/login",
    "glassdoor": "https://www.glassdoor.com/profile/login_input.htm",
    "indeed": "https://secure.indeed.com/auth",
}

SITE_DOMAINS = {
    "linkedin": [".linkedin.com"],
    "glassdoor": [".glassdoor.com"],
    "indeed": [".indeed.com", ".secure.indeed.com"],
}


def get_config(force_headless: bool = False) -> dict:
    env_val = os.getenv("HEADLESS")
    headless = True
    if env_val is not None and env_val.upper() == "FALSE":
        headless = False
    if force_headless:
        headless = True
    return {"headless": headless}


async def create_context(pw, force_headless: bool = False):
    config = get_config(force_headless)
    if _another_instance_active():
        msg = (
            "Outra instancia do JobPilot esta usando bot_profile (lock fresco detectado). "
            "Rodar apply e connect ao mesmo tempo com o mesmo perfil causa crash do Chrome. "
            "Espere a outra terminar ou stagger os agendamentos."
        )
        logger.error(msg)
        raise RuntimeError(msg)
    logger.info(f"Launching Chrome (headless={config['headless']})")
    _clear_chrome_locks()

    last_err: Exception | None = None
    for attempt in range(1, _LAUNCH_RETRIES + 2):  # 1 initial + N retries
        try:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=BOT_PROFILE_DIR,
                headless=config["headless"],
                channel="chrome",
                args=["--start-maximized"],
                no_viewport=True,
                timeout=_LAUNCH_TIMEOUT_MS,
            )
            logger.info("Chrome launched")
            break
        except Exception as e:
            last_err = e
            logger.warning(
                f"Chrome launch attempt {attempt}/{_LAUNCH_RETRIES + 1} failed: {e}"
            )
            if attempt > _LAUNCH_RETRIES:
                logger.error("Chrome launch exhausted retries")
                raise
            await asyncio.sleep(_RETRY_WAIT_S)
            _clear_chrome_locks()
    else:
        raise last_err  # unreachable, but mypy-friendly

    logger.info("Applying stealth patches")
    await _stealth.apply_stealth_async(context)
    page = context.pages[0] if context.pages else await context.new_page()
    logger.info("Context ready")
    return context, page


async def run_login(site: str):
    url = LOGIN_URLS[site]
    print(f"Opening {url}...", flush=True)
    async with async_playwright() as pw:
        context, page = await create_context(pw, force_headless=False)
        try:
            await page.goto(url, wait_until="domcontentloaded")
            print(f"Browser opened at {url}", flush=True)
            print("Log in and close the browser window when done.", flush=True)
            while True:
                try:
                    if len(context.pages) == 0:
                        break
                    await page.wait_for_timeout(1000)
                except Exception:
                    break
            print("Browser closed. Login session saved.", flush=True)
        finally:
            try:
                await context.close()
            except Exception:
                pass


async def run_logout(site: str):
    domains = SITE_DOMAINS[site]
    login_url = LOGIN_URLS[site]
    async with async_playwright() as pw:
        context, page = await create_context(pw, force_headless=False)
        try:
            await page.goto(login_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            removed = 0
            for cookie in await context.cookies():
                domain = cookie.get("domain", "")
                if any(domain.endswith(d.lstrip(".")) or domain == d for d in domains):
                    removed += 1
                    await context.clear_cookies()
                    break
            print(f"Cleared {removed} cookie(s) for {site}.")
            print(f"Session removed. Run 'login {site}' to log in again.")
        finally:
            await context.close()


async def run_browser(work, *, headless: bool = False):
    """Run ``work(page)`` inside a Playwright context with screenshot + cleanup.

    ``work`` is an async callable that receives the page object.
    Screenshot is taken on both success and error; context is always closed.
    """
    async with async_playwright() as pw:
        context, page = await create_context(pw, force_headless=headless)
        try:
            await work(page)
            try:
                await page.screenshot(path=f"{setting.screenshots_path}.png")
            except Exception:
                pass
        except Exception as e:
            logger.critical(f"{str(e)}")
            try:
                await page.screenshot(path=f"{setting.screenshots_path}.png")
            except Exception:
                pass
            raise
        finally:
            try:
                await context.close()
            except Exception:
                pass


async def run_browser_simple(work, *, headless: bool = False, post_wait_ms: int = 0):
    """Run ``work(page)`` inside a Playwright context — no screenshot, no critical log.

    Lighter wrapper for ad-hoc tasks (e.g. test-apply). Optionally waits
    ``post_wait_ms`` before closing so the user can inspect the final state.
    """
    async with async_playwright() as pw:
        context, page = await create_context(pw, force_headless=headless)
        try:
            await work(page)
        finally:
            if post_wait_ms > 0:
                try:
                    await page.wait_for_timeout(post_wait_ms)
                except Exception:
                    pass
            try:
                await context.close()
            except Exception:
                pass
