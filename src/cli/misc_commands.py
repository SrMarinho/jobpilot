import asyncio
from typing import Optional

import typer

from src.utils.logger import set_run_context
from src.cli.persistence import _find_resume
from src.cli.browser import _create_context, _create_context_sync, run_login, run_logout
from src.cli.enums import SiteName
from src.cli.misc_logic import read_resume_text, run_test_apply_browser


def register_misc_commands(app: typer.Typer) -> None:
    @app.command()
    def login(site: SiteName):
        """Open browser to log in to a job site (linkedin, glassdoor, indeed)."""
        asyncio.run(run_login(site.value))

    @app.command()
    def logout(site: SiteName):
        """Clear saved session for a site."""
        asyncio.run(run_logout(site.value))

    @app.command("test-apply")
    def test_apply(
        ctx: typer.Context,
        job_url: str = typer.Argument(..., help="LinkedIn job URL (e.g. https://www.linkedin.com/jobs/view/1234567890)"),
        resume: Optional[str] = typer.Option(None, "--resume", help="Path to resume file (default: resume.txt)"),
        no_submit: bool = typer.Option(False, "--no-submit", help="Fill forms but do not submit"),
    ):
        """Test Easy Apply on a specific job URL (skips evaluation)."""
        set_run_context("test-apply")
        resume_path = resume or "resume.txt"
        resume_text = read_resume_text(resume_path)

        async def _run():
            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                context, page = await _create_context(pw, force_headless=False)
                try:
                    success = await run_test_apply_browser(page, job_url, resume_text, no_submit)
                    if no_submit:
                        print("Dry run complete — form was filled but not submitted.")
                    else:
                        print(f"Result: {'SUCCESS' if success else 'FAILED'}")
                finally:
                    try:
                        await page.wait_for_timeout(3000)
                    except EOFError:
                        pass
                    await context.close()

        asyncio.run(_run())

    @app.command()
    def bot(
        resume: str = typer.Option(_find_resume(), "--resume", help="Path to resume file"),
    ):
        """Start Telegram bot to control JobPilot remotely."""
        set_run_context("bot")
        from src.bot.telegram_bot import TelegramBot
        TelegramBot(driver_factory=lambda: _create_context_sync(), resume_path=resume).run()
