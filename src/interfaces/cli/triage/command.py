import typer
from rich.console import Console

from src.automation.tasks.job_triage import triage_job
from src.core.use_cases.job_evaluator import JobEvaluator
from src.interfaces.cli.browser import run_browser_task
from src.interfaces.cli.persistence import _find_resume

console = Console()


def register_triage_command(app: typer.Typer) -> None:
    @app.command("triage")
    def cmd_triage(
        ctx: typer.Context,
        url: str = typer.Argument(..., help="URL da vaga"),
        resume: str = typer.Option("", "--resume", help="Currículo (PDF/TXT)"),
        preferences: str = typer.Option("", "--preferences", help="Preferências"),
        no_cache: bool = typer.Option(
            False, "--no-cache", help="Reavalia mesmo se já avaliada"
        ),
        telegram: bool = typer.Option(False, "--telegram", help="Manda no Telegram"),
    ):
        """Avalia uma vaga pelo link, sem candidatar.

        Pro caso "achei essa vaga, vale a pena?": responde match, salário
        estimado e gaps de skill. O resultado entra na mesma fila do
        'jobs apply', então a vaga não é reavaliada depois.
        """
        evaluator = JobEvaluator(_find_resume(resume), preferences=preferences)
        holder: list = []

        async def _work(page):
            holder.append(
                await triage_job(page, url, evaluator=evaluator, use_cache=not no_cache)
            )

        run_browser_task(ctx, "triage", _work)

        if not holder:
            console.print("[red]Triagem não completou.[/red]")
            raise typer.Exit(code=1)

        result = holder[0]
        if result.error:
            console.print(f"[red]{result.error}[/red]")
            raise typer.Exit(code=1)

        veredito = (
            "[green]✅ MATCH[/green]"
            if result.result.matches
            else "[red]❌ NÃO BATE[/red]"
        )
        console.print(f"\n{veredito}  [dim]({result.site})[/dim]")
        console.print(f"[bold]{result.title}[/bold]")
        if result.company:
            console.print(f"🏢 {result.company}")
        if result.result.salary:
            salario = f"{result.result.salary:,}".replace(",", ".")
            console.print(f"💰 R$ {salario}{result.result.contract_tag}")
        console.print(f"\n💬 {result.result.reason}")
        if result.result.missing_skills:
            console.print(f"🎯 Gaps: {', '.join(result.result.missing_skills)}")
        if result.from_cache:
            console.print("[dim](avaliação reaproveitada do histórico)[/dim]")

        if telegram:
            from src.utils.telegram import send_telegram

            send_telegram(result.as_telegram(), topic="status")
