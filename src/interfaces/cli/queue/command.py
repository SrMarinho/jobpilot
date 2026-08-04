import typer
from rich.console import Console
from rich.table import Table

from src.core.use_cases.applied_jobs_tracker import AppliedJobsTracker
from src.core.use_cases.evaluated_jobs_tracker import EvaluatedJobsTracker

console = Console()


def register_queue_command(app: typer.Typer) -> None:
    @app.command("queue")
    def cmd_queue(
        limit: int = typer.Option(20, "--limit", help="Quantas vagas listar"),
        site: str = typer.Option("", "--site", help="Filtra por site"),
        stats: bool = typer.Option(False, "--stats", help="Só o resumo do funil"),
    ):
        """Vagas aprovadas pelo LLM que ainda não viraram candidatura.

        Antes o veredito do LLM morria no fim do run: tudo que foi aprovado mas
        não deu pra aplicar (limite batido, formulário travado, run interrompido)
        sumia. Aqui fica a fila, ordenada pelo salário estimado.
        """
        evaluations = EvaluatedJobsTracker()
        resumo = evaluations.stats()

        applied = AppliedJobsTracker()
        aplicadas = set(applied._applied)

        console.print(
            f"[bold]Funil:[/bold] {resumo['evaluated']} avaliadas · "
            f"[green]{resumo['approved']} aprovadas[/green] · "
            f"[dim]{resumo['rejected']} rejeitadas[/dim] · "
            f"{len(aplicadas)} aplicadas"
        )
        if resumo["avg_salary"]:
            console.print(
                f"Salário médio das aprovadas: R$ {resumo['avg_salary']:,}".replace(
                    ",", "."
                )
            )
        if stats:
            return

        fila = evaluations.queue(applied_ids=aplicadas)
        if site:
            fila = [job for job in fila if job.site == site]
        if not fila:
            console.print("\n[yellow]Fila vazia.[/yellow] Rode 'jobs apply' primeiro.")
            return

        table = Table(title=f"Fila de vagas ({len(fila)} em aberto)")
        table.add_column("#", justify="right")
        table.add_column("Vaga")
        table.add_column("Empresa")
        table.add_column("Salário", justify="right")
        table.add_column("Site")
        table.add_column("Gaps")

        for i, job in enumerate(fila[:limit], 1):
            salario = f"R$ {job.salary:,}".replace(",", ".") if job.salary else "—"
            gaps = ", ".join(job.missing_skills[:3]) or "—"
            table.add_row(
                str(i),
                job.title[:45],
                job.company[:22] or "—",
                f"{salario}{job.contract_tag}",
                job.site,
                gaps,
            )
        console.print(table)
        if len(fila) > limit:
            console.print(f"[dim]... e mais {len(fila) - limit}. Use --limit.[/dim]")
        console.print("\n[dim]URLs:[/dim]")
        for i, job in enumerate(fila[:limit], 1):
            console.print(f"[dim]{i:>2}.[/dim] {job.url}")
