import typer
from rich.console import Console
from rich.table import Table

from src.config.settings import logger
from src.core.use_cases.selector_canary import (
    CanaryReport,
    check_linkedin_feed,
    check_linkedin_jobs,
    check_linkedin_people,
    check_profile_analytics,
)
from src.interfaces.cli.browser import run_browser_task

console = Console()

DEFAULT_SEARCH_URL = (
    "https://www.linkedin.com/jobs/search/?keywords=desenvolvedor%20backend"
    "&f_AL=true&f_WT=2"
)
DEFAULT_PEOPLE_URL = (
    "https://www.linkedin.com/search/results/people/?keywords=recrutador%20tech"
)


def register_canary_command(app: typer.Typer) -> None:
    @app.command("selectors-check")
    def cmd_selectors_check(
        ctx: typer.Context,
        url: str = typer.Option(
            DEFAULT_SEARCH_URL, "--url", help="Busca de vagas usada na verificação"
        ),
        skip_feed: bool = typer.Option(False, "--skip-feed", help="Pula o feed"),
        skip_people: bool = typer.Option(
            False, "--skip-people", help="Pula a busca de pessoas"
        ),
        skip_analytics: bool = typer.Option(
            False, "--skip-analytics", help="Pula as páginas de analytics"
        ),
        telegram: bool = typer.Option(
            False, "--telegram", help="Manda o resultado no Telegram"
        ),
        scheduled: bool = typer.Option(
            False, "--scheduled", help="Modo agendado: só avisa quando algo quebra"
        ),
    ):
        """Verifica se os selectors das páginas críticas ainda resolvem.

        Não age em nada — só abre as páginas e confere que os campos aparecem.
        Serve pra descobrir quebra de layout ANTES do run agendado falhar em
        silêncio (scraper devolvendo vazio é o modo de falha mais comum aqui).
        """
        report = CanaryReport()

        async def _work(page):
            await check_linkedin_jobs(page, report, url)
            if not skip_feed:
                await check_linkedin_feed(page, report)
            if not skip_people:
                await check_linkedin_people(page, report, DEFAULT_PEOPLE_URL)
            if not skip_analytics:
                await check_profile_analytics(page, report)

        run_browser_task(ctx, "selectors-check", _work)
        _render(report)

        if telegram and (report.failures or not scheduled):
            # No modo agendado só notifica quebra — canário verde toda noite
            # vira ruído e some no meio das outras mensagens.
            from src.utils.telegram import send_telegram

            send_telegram(report.as_telegram(), topic="alerts")

        if report.failures:
            logger.error(f"Canário: {len(report.failures)} selector(s) quebrado(s)")
            raise typer.Exit(code=1)


def _render(report: CanaryReport) -> None:
    if not report.results:
        console.print("[yellow]Nada verificado.[/yellow]")
        return
    table = Table(title=f"Canário de selectors — {report.summary()}")
    table.add_column("Página")
    table.add_column("Campo")
    table.add_column("Status")
    table.add_column("Detalhe")
    for result in report.results:
        table.add_row(
            result.page,
            result.field,
            "[green]OK[/green]" if result.ok else "[red]QUEBROU[/red]",
            result.detail,
        )
    console.print(table)
    if report.healthy:
        console.print("[green]Nenhuma quebra de layout detectada.[/green]")
    else:
        console.print(
            f"[red]{len(report.failures)} selector(s) quebrado(s).[/red] "
            "Os runs que dependem desses campos vão falhar em silêncio."
        )
