from typing import Optional

import typer

from src.utils.async_utils import run_async
from src.utils.logger import set_run_context
from src.interfaces.cli.autopost.logic import (
    resolve_autopost_config,
    run_autopost,
    run_publish_approved,
    run_publish_one,
    run_daily,
    run_regen_image,
    list_drafts,
    list_posted,
    approve_draft,
)


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
            False,
            "--force",
            help="Ignora o guard 'já postou hoje' (publica mesmo assim)",
        ),
        daily: bool = typer.Option(
            False,
            "--daily",
            help="Orquestrador diário (logon): 1 post/dia — publica aprovado, "
            "avisa se só há pendente, ou gera novo se fila vazia",
        ),
        list_drafts_opt: bool = typer.Option(
            False, "--list", help="Lista drafts pendentes + aprovados com ids"
        ),
        list_posted_opt: bool = typer.Option(
            False, "--list-posted", help="Lista drafts já publicados (postados) com ids"
        ),
        publish: Optional[str] = typer.Option(
            None,
            "--publish",
            is_flag=False,
            flag_value="__APPROVED__",
            help="Publica: SEM valor = drena Telegram + FIFO 1 aprovado; "
            "COM <id> = publica esse draft e marca postado",
        ),
        regen_image: Optional[str] = typer.Option(
            None,
            "--regen-image",
            help="Regera a imagem (card local on-brand) de um draft por id",
        ),
        approve: Optional[str] = typer.Option(
            None, "--approve", help="Aprova um draft por id via CLI (publica depois)"
        ),
        count: int = typer.Option(
            1, "--count", help="Quantos drafts gerar no run (batch, dedup entre eles)"
        ),
        expires_hours: int = typer.Option(
            0,
            "--expires-hours",
            help="Janela de aprovação em horas (0 = sem expirar)",
        ),
    ):
        """Gera post autoral via LLM e envia para aprovação no Telegram."""
        set_run_context("autopost")

        if list_drafts_opt:
            list_drafts()
            return
        if list_posted_opt:
            list_posted()
            return
        if approve:
            approve_draft(approve)
            return
        if regen_image:
            run_async(run_regen_image(regen_image))
            return
        if daily:
            run_async(run_daily(force=force))
            return
        if publish is not None:
            if publish == "__APPROVED__":
                run_async(run_publish_approved())
            else:
                run_async(run_publish_one(publish))
            return

        cfg = resolve_autopost_config(
            source=source,
            topic=topic,
            fmt=fmt,
            dry_run=dry_run,
            no_telegram=no_telegram,
            scheduled=scheduled,
            force=force,
            count=count,
            expires_hours=expires_hours,
        )
        if cfg is None:
            return  # skip-today exit 0
        run_async(run_autopost(cfg))
