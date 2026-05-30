from pathlib import Path as _Path


import asyncio
from typing import Optional

import typer

from src.utils.logger import set_run_context
from src.interfaces.cli.persistence import _find_resume
from src.interfaces.cli.browser import (
    _create_context,
    _create_context_sync,
    run_login,
    run_logout,
)
from src.interfaces.cli.enums import SiteName


def read_resume_text(resume_path: str) -> str:
    rp = _Path(resume_path)
    if rp.suffix.lower() == ".pdf":
        from pypdf import PdfReader as _PdfReader

        return "\n".join(p.extract_text() or "" for p in _PdfReader(resume_path).pages)
    return rp.read_text(encoding="utf-8")


async def run_test_apply_browser(
    page, job_url: str, resume_text: str, no_submit: bool
) -> bool:
    from src.automation.tasks.job_application_manager import _detect_site

    site = _detect_site(job_url)
    print(f"Site detected: {site}")

    await page.goto(job_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    if site == "indeed":
        from src.automation.pages.indeed_jobs_page import IndeedJobsPage
        from src.core.use_cases.indeed_application_handler import (
            IndeedApplicationHandler,
        )

        page_obj = IndeedJobsPage(page, job_url)
        btn = await page_obj.get_apply_btn()
        if not btn:
            print("No Apply button found on this Indeed job page.")
            return False
        title = await page_obj.get_job_title() or "Test Job"
        print(f"Applying to: {title}")
        await btn.click()
        await page.wait_for_timeout(1500)
        handler = IndeedApplicationHandler(page, resume=resume_text)
        return await handler.submit(salary_expectation=None, no_submit=no_submit)
    else:
        from src.automation.pages.jobs_search_page import JobsSearchPage
        from src.core.use_cases.job_application_handler import JobApplicationHandler

        page_obj = JobsSearchPage(page, job_url)
        btn = await page_obj.get_easy_apply_btn()
        if not btn:
            print("No Easy Apply button found on this job page.")
            return False
        title = await page_obj.get_job_title() or "Test Job"
        description = await page_obj.get_job_description() or ""
        print(f"Applying to: {title}")
        await btn.click()
        await page.wait_for_timeout(1500)
        handler = JobApplicationHandler(page, resume=resume_text)
        return await handler.submit_easy_apply(
            job_title=title, job_description=description, no_submit=no_submit
        )


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
        job_url: str = typer.Argument(
            ...,
            help="LinkedIn job URL (e.g. https://www.linkedin.com/jobs/view/1234567890)",
        ),
        resume: Optional[str] = typer.Option(
            None, "--resume", help="Path to resume file (default: resume.txt)"
        ),
        no_submit: bool = typer.Option(
            False, "--no-submit", help="Fill forms but do not submit"
        ),
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
                    success = await run_test_apply_browser(
                        page, job_url, resume_text, no_submit
                    )
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
        resume: str = typer.Option(
            _find_resume(), "--resume", help="Path to resume file"
        ),
    ):
        """Start Telegram bot to control JobPilot remotely."""
        set_run_context("bot")
        from src.bot.telegram_bot import TelegramBot

        TelegramBot(
            driver_factory=lambda: _create_context_sync(), resume_path=resume
        ).run()
