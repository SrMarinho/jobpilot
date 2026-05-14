import asyncio
from typing import Optional

import typer
from playwright.async_api import async_playwright

import src.config.settings as setting
from src.utils.logger import set_run_context
from src.config.settings import logger
from src.automation import url_builder as _url_builder
from src.cli.persistence import (
    load_last_urls, save_last_url,
    is_already_ran_today, is_weekly_limit_reached,
    save_ran_today,
)
from src.cli.browser import _create_context
from src.cli.enums import NetworkDegree
from src.cli.connect_logic import run_connect_browser


def register_connect_command(app: typer.Typer) -> None:
    @app.command()
    def connect(
        ctx: typer.Context,
        url: Optional[str] = typer.Option(None, "--url", "-u", help="Full LinkedIn people search URL (overrides --keywords)"),
        keywords: Optional[str] = typer.Option(None, "--keywords", "-k", help="Search keywords (e.g. 'tech recruiter')"),
        network: Optional[NetworkDegree] = typer.Option(None, "--network", help="Connection degree filter (F=1st, S=2nd, O=3rd+)"),
        start_page: Optional[int] = typer.Option(None, "--start-page", help="Page to start from (default: 1)"),
        max_pages: int = typer.Option(100, "--max-pages", help="Max pages to process (default: 100)"),
        resume: bool = typer.Option(False, "--continue", help="Resume from the last page where it stopped"),
        scheduled: bool = typer.Option(False, "--scheduled", help="Scheduled mode: skip if already ran today or weekly limit reached"),
    ):
        """Send connection requests (LinkedIn people search)."""
        set_run_context("connect")
        headless = ctx.obj.get("headless", False)
        last_urls = load_last_urls()
        site_key = "connect"
        saved: dict = last_urls.get(site_key, {})

        if scheduled:
            if is_already_ran_today():
                logger.info("Already ran today. Skipping.")
                return
            if is_weekly_limit_reached():
                logger.info("Weekly connection limit already reached this week. Skipping.")
                return
            save_ran_today()

        k_network = network.value if network else None

        if url:
            resolved_url = url
            resolved_start_page = start_page or 1
        elif keywords:
            resolved_url = _url_builder.build_linkedin_people_url(keywords, network=k_network)
            resolved_start_page = start_page or 1
            print(f"Using search: keywords='{keywords}'" + (f", network={k_network}" if k_network else ""))
        else:
            saved_keywords = saved.get("keywords") if isinstance(saved, dict) else None
            if saved_keywords:
                resolved_url = _url_builder.build_linkedin_people_url(
                    saved_keywords, network=saved.get("network"),
                )
            else:
                resolved_url = saved.get("url") if isinstance(saved, dict) else None
            if not resolved_url:
                print("Error: pass --url or --keywords for the first 'connect' run.")
                raise typer.Exit()

            if resume:
                resolved_start_page = saved.get("page", 1) if isinstance(saved, dict) else 1
                print(f"Resuming 'connect' from page {resolved_start_page}: {resolved_url}")
            else:
                resolved_start_page = start_page or 1
                print(f"Using last saved search for 'connect': {resolved_url}")

        if resolved_url and (url or keywords or not saved.get("url")):
            extra = {}
            if keywords:
                extra["keywords"] = keywords
            if k_network:
                extra["network"] = k_network
            save_last_url(site_key, resolved_url, page=1, extra=extra if extra else None)

        final_network = k_network or (saved.get("network") if isinstance(saved, dict) else None)
        final_keywords = keywords or (saved.get("keywords") if isinstance(saved, dict) else None)

        def on_page_change(page: int):
            extra = {}
            if final_keywords:
                extra["keywords"] = final_keywords
            if final_network:
                extra["network"] = final_network
            save_last_url(site_key, resolved_url, page=page, extra=extra if extra else None)

        async def _run():
            async with async_playwright() as pw:
                context, page = await _create_context(pw, force_headless=headless)
                try:
                    await run_connect_browser(page, resolved_url, max_pages, resolved_start_page, on_page_change)
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

        asyncio.run(_run())
