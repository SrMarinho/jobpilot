import os
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from filelock import FileLock, Timeout

from src.automation.checkpoint import CheckpointError
from src.utils.async_utils import run_async
from src.utils.logger import set_run_context
from src.config.settings import logger
import src.config.settings as setting
from src.interfaces.cli.persistence import BOT_PROFILE_DIR

_stealth = Stealth()

_LAUNCH_TIMEOUT_MS = 90_000
_LAUNCH_RETRIES = 2
_RETRY_WAIT_S = 5
_LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")

# ── App-level browser lock (cross-process queue) ──────────────────
# Only one JobPilot browser session may use bot_profile at a time. A
# scheduled run that finds the lock held waits in line until it frees,
# instead of colliding with the live Chrome and dying. filelock releases
# automatically if the holding process crashes (OS-level handle).
_APP_LOCK_PATH = str(Path(BOT_PROFILE_DIR).parent / "bot_profile.lock")
_LOCK_MAX_WAIT_S = 3600  # give up after 1h in queue
_LOCK_POLL_S = 5


async def acquire_browser_lock(label: str = "browser") -> FileLock:
    """Acquire the exclusive browser lock, queuing if another run holds it.

    Returns the held FileLock — caller MUST ``release()`` it in a finally.
    """
    lock = FileLock(_APP_LOCK_PATH, thread_local=False)
    waited = 0
    while True:
        try:
            lock.acquire(blocking=False)
            logger.info(f"Browser lock adquirido ({label})")
            return lock
        except Timeout:
            if waited == 0:
                logger.info(
                    f"Browser ocupado por outra instancia. {label} na fila, aguardando..."
                )
            await asyncio.sleep(_LOCK_POLL_S)
            waited += _LOCK_POLL_S
            if waited % 30 == 0:
                logger.info(f"{label} ainda na fila... ({waited}s)")
            if waited >= _LOCK_MAX_WAIT_S:
                raise RuntimeError(
                    f"Espera de browser lock excedeu {_LOCK_MAX_WAIT_S}s ({label})"
                )


def _release_browser_lock(lock: FileLock, label: str = "browser") -> None:
    try:
        lock.release()
        logger.info(f"Browser lock liberado ({label})")
    except Exception as e:
        logger.warning(f"Falha ao liberar browser lock ({label}): {e}")


def _clear_chrome_locks() -> None:
    """Remove orphan Chrome singleton lock files from a previous crashed run.

    Safe to clear unconditionally: the app-level browser lock guarantees no
    other JobPilot instance is using bot_profile right now, so any singleton
    lock present is an orphan.
    """
    profile = Path(BOT_PROFILE_DIR)
    if not profile.exists():
        return
    for name in _LOCK_FILES:
        lock = profile / name
        try:
            if not (lock.exists() or lock.is_symlink()):
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
    lock = await acquire_browser_lock("login")
    try:
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
    finally:
        _release_browser_lock(lock, "login")


async def run_logout(site: str):
    domains = SITE_DOMAINS[site]
    login_url = LOGIN_URLS[site]
    lock = await acquire_browser_lock("logout")
    try:
        async with async_playwright() as pw:
            context, page = await create_context(pw, force_headless=False)
            try:
                await page.goto(login_url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)
                # Só os cookies do site pedido — o perfil Chrome é compartilhado
                # entre linkedin/glassdoor/indeed, então limpar tudo derrubaria
                # as sessões dos outros sites.
                removed = 0
                targets: set[str] = set()
                for cookie in await context.cookies():
                    domain = cookie.get("domain", "")
                    if any(
                        domain.endswith(d.lstrip(".")) or domain == d for d in domains
                    ):
                        removed += 1
                        targets.add(domain)
                for domain in targets:
                    await context.clear_cookies(domain=domain)
                print(f"Cleared {removed} cookie(s) for {site}.")
                print(f"Session removed. Run 'login {site}' to log in again.")
            finally:
                await context.close()
    finally:
        _release_browser_lock(lock, "logout")


def run_browser_task(ctx, name: str, work) -> None:
    """Entrada padrão de todo comando CLI que precisa de browser.

    Faz o que os 13 comandos repetiam linha por linha: nomeia o run no log,
    lê ``--headless`` do contexto do Typer e roda ``work(page)`` sob o browser
    lock. Não é decorator de propósito — o Typer inspeciona a assinatura da
    função de comando, e envolvê-la exigiria preservar assinatura à mão.
    """
    set_run_context(name)
    run_async(run_browser(work, headless=ctx.obj.get("headless", False)))


async def run_browser(work, *, headless: bool = False):
    """Run ``work(page)`` inside a Playwright context with screenshot + cleanup.

    ``work`` is an async callable that receives the page object.
    Screenshot is taken on both success and error; context is always closed.
    Serialized via the app-level browser lock (queues if another run holds it).
    """
    lock = await acquire_browser_lock("run_browser")
    try:
        async with async_playwright() as pw:
            context, page = await create_context(pw, force_headless=headless)
            try:
                await work(page)
                try:
                    await page.screenshot(path=f"{setting.screenshots_path}.png")
                except Exception:
                    pass
            except CheckpointError as e:
                # Não é crash: a conta caiu num checkpoint e a automação parou
                # de propósito. O alerta no Telegram já saiu em ensure_not_blocked.
                logger.error(
                    f"Checkpoint do LinkedIn ({e}) — resolva a verificação "
                    "manualmente no Chrome antes do próximo run."
                )
                try:
                    await page.screenshot(path=f"{setting.screenshots_path}.png")
                except Exception:
                    pass
                raise
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
    finally:
        _release_browser_lock(lock, "run_browser")


async def run_browser_simple(work, *, headless: bool = False, post_wait_ms: int = 0):
    """Run ``work(page)`` inside a Playwright context — no screenshot, no critical log.

    Lighter wrapper for ad-hoc tasks (e.g. test-apply). Optionally waits
    ``post_wait_ms`` before closing so the user can inspect the final state.
    Serialized via the app-level browser lock.
    """
    lock = await acquire_browser_lock("run_browser_simple")
    try:
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
    finally:
        _release_browser_lock(lock, "run_browser_simple")
