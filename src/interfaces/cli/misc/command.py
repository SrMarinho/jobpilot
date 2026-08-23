from typing import Optional

import typer

from src.utils.logger import set_run_context
from src.utils.async_utils import run_async
from src.interfaces.cli.persistence import _find_resume
from src.interfaces.cli.browser import run_browser_simple, run_login, run_logout
from src.interfaces.cli.enums import SiteName
from src.interfaces.cli.misc.logic import read_resume_text
from src.automation.tasks.test_apply import run_test_apply


def register_misc_commands(app: typer.Typer) -> None:
    """Registers top-level utility commands: login, logout, bot."""

    @app.command()
    def login(site: SiteName):
        """Open browser to log in to a job site (linkedin, glassdoor, indeed)."""
        run_async(run_login(site.value))

    @app.command()
    def logout(site: SiteName):
        """Clear saved session for a site."""
        run_async(run_logout(site.value))

    @app.command()
    def bot(
        resume: str = typer.Option(
            _find_resume(), "--resume", help="Path to resume file"
        ),
    ):
        """Start Telegram bot to control JobPilot remotely."""
        set_run_context("bot")
        from src.bot.telegram_bot import TelegramBot

        TelegramBot(resume_path=resume).run()


def register_test_apply_command(app: typer.Typer) -> None:
    """Registers the test-apply command under any given Typer app."""

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
        resume_text = read_resume_text(resume or "resume.txt")
        result = {"success": False}

        async def _work(page):
            result["success"] = await run_test_apply(
                page, job_url, resume_text, no_submit
            )

        run_async(run_browser_simple(_work, headless=False, post_wait_ms=3000))
        if no_submit:
            # no_submit para no modal aberto, antes de preencher: dizer que
            # o formulario foi preenchido esconde que nada foi exercitado.
            print("Modal aberto. Nada preenchido nem enviado (--no-submit).")
        else:
            print(f"Result: {'SUCCESS' if result['success'] else 'FAILED'}")
