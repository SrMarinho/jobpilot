from typing import Optional

import typer

from src.interfaces.cli.browser import run_browser_task
from src.interfaces.cli.followup.logic import (
    resolve_followup_config,
    run_followup_browser,
)


def register_followup_command(app: typer.Typer) -> None:
    @app.command()
    def followup(
        ctx: typer.Context,
        max_dms: int = typer.Option(5, "--max-dms", help="Máx DMs por run (default 5)"),
        resume: Optional[str] = typer.Option(
            None, "--resume", help="Override resume path (default: auto)"
        ),
        scheduled: bool = typer.Option(
            False, "--scheduled", help="Scheduled mode: skip if already ran today"
        ),
        force: bool = typer.Option(False, "--force", help="Ignora skip-today (debug)"),
    ):
        """Follow-up DM pós-conexão: gera DMs p/ conexões novas e manda pro Telegram."""

        cfg = resolve_followup_config(resume, max_dms, scheduled, force)
        if cfg is None:
            return

        async def _work(page):
            await run_followup_browser(page, cfg)

        run_browser_task(ctx, "followup", _work)
