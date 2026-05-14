import os
import asyncio

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from src.cli.persistence import BOT_PROFILE_DIR

_stealth = Stealth()

LOGIN_URLS = {
    "linkedin": "https://www.linkedin.com/login",
    "glassdoor": "https://www.glassdoor.com/profile/login_input.htm",
    "indeed": "https://secure.indeed.com/auth",
}

SITE_DOMAINS = {
    "linkedin":  [".linkedin.com"],
    "glassdoor": [".glassdoor.com"],
    "indeed":    [".indeed.com", ".secure.indeed.com"],
}


def get_config(force_headless: bool = False) -> dict:
    env_val = os.getenv("HEADLESS")
    headless = True
    if env_val is not None and env_val.upper() == "FALSE":
        headless = False
    if force_headless:
        headless = True
    return {"headless": headless}


async def _create_context(pw, force_headless: bool = False):
    config = get_config(force_headless)
    context = await pw.chromium.launch_persistent_context(
        user_data_dir=BOT_PROFILE_DIR,
        headless=config["headless"],
        channel="chrome",
        args=["--start-maximized"],
        no_viewport=True,
    )
    await _stealth.apply_stealth_async(context)
    page = context.pages[0] if context.pages else await context.new_page()
    return context, page


def _create_context_sync(force_headless: bool = False):
    """Synchronous factory for TelegramBot (runs in threads)."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    config = get_config(force_headless)
    context = pw.chromium.launch_persistent_context(
        user_data_dir=BOT_PROFILE_DIR,
        headless=config["headless"],
        channel="chrome",
        args=["--start-maximized"],
        no_viewport=True,
    )
    _stealth.apply_stealth_sync(context)
    page = context.pages[0] if context.pages else context.new_page()
    return pw, context, page


async def run_login(site: str):
    url = LOGIN_URLS[site]
    print(f"Opening {url}...", flush=True)
    async with async_playwright() as pw:
        context, page = await _create_context(pw, force_headless=False)
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
        context, page = await _create_context(pw, force_headless=False)
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
