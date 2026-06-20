from typing import Optional

import typer

from src.utils.async_utils import run_async
from src.utils.logger import set_run_context
from src.interfaces.cli.autopost.logic import resolve_autopost_config, run_autopost


def register_autopost_command(app: typer.Typer) -> None:
    @app.command()
    def autopost(
        source: Optional[str] = typer.Option(
            None, "--source", help="template|commit|rss|manual (default: por weekday)"
        ),
        topic: Optional[str] = typer.Option(
            None, "--topic", help="Tema custom (obrigatório se --source manual)"
        ),
        fmt: Optional[str] = typer.Option(
            None, "--format", help="snippet|story|dissertativo|contrarian"
        ),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Gera + envia preview, mas não publica"
        ),
        no_telegram: bool = typer.Option(
            False, "--no-telegram", help="Gera + imprime no stdout (debug)"
        ),
        scheduled: bool = typer.Option(
            False, "--scheduled", help="Scheduled mode: skip se já rodou hoje"
        ),
        force: bool = typer.Option(
            False, "--force", help="Ignora skip-today guard (debug)"
        ),
    ):
        """Gera post autoral via LLM e envia para aprovação no Telegram."""
        set_run_context("autopost")
        cfg = resolve_autopost_config(
            source=source,
            topic=topic,
            fmt=fmt,
            dry_run=dry_run,
            no_telegram=no_telegram,
            scheduled=scheduled,
            force=force,
        )
        if cfg is None:
            return  # skip-today exit 0
        run_async(run_autopost(cfg))
