from typing import List, Optional

import typer

from src.interfaces.cli.browser import run_browser_task
from src.interfaces.cli.hired.logic import run_hired_browser


def register_hired_command(app: typer.Typer) -> None:
    @app.command()
    def hired(
        ctx: typer.Context,
        role: List[str] = typer.Option(
            ...,
            "--role",
            "-r",
            help="Cargo-alvo (repetível: -r 'Software Engineer' -r 'Backend')",
        ),
        days: int = typer.Option(
            90, "--days", help="Janela de recência da contratação (dias, default 90)"
        ),
        max_profiles: int = typer.Option(
            10, "--max-profiles", "-n", help="Máx. perfis a abrir/coletar"
        ),
        out: Optional[str] = typer.Option(
            None, "--out", help="Exporta perfis coletados p/ CSV neste caminho"
        ),
        gap: bool = typer.Option(
            False, "--gap", help="Compara skills em alta com teu currículo (lacunas)"
        ),
        resume: Optional[str] = typer.Option(
            None, "--resume", help="Caminho do currículo p/ o gap (default: auto)"
        ),
        trend: bool = typer.Option(
            False, "--trend", help="Tendência das skills (subindo/caindo mês a mês)"
        ),
        telegram: bool = typer.Option(
            False, "--telegram", help="Envia o relatório completo via Telegram"
        ),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Só descobre/loga anúncios; não abre perfis"
        ),
        no_dedup: bool = typer.Option(
            False, "--no-dedup", help="Ignora dedup: re-coleta perfis já vistos"
        ),
    ):
        """Analisa quem foi contratado recentemente p/ um cargo e agrega as skills.

        Descobre posts de anúncio de contratação (<=N dias), abre cada perfil só
        p/ ler as competências principais, deduplica por perfil e imprime o
        ranking de skills mais frequentes — benchmark p/ ajustar seu perfil.
        """

        async def _work(page):
            await run_hired_browser(
                page,
                list(role),
                days,
                max_profiles,
                dry_run,
                out,
                gap,
                resume,
                trend,
                telegram,
                no_dedup,
            )

        run_browser_task(ctx, "hired", _work)
