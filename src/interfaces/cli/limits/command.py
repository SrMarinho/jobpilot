import typer
from rich.console import Console
from rich.table import Table

from src.core.use_cases.rate_limiter import DEFAULT_QUOTAS, RateLimiter
from src.core.use_cases.run_guard import check_run, within_active_hours

console = Console()


def register_limits_command(app: typer.Typer) -> None:
    @app.command("limits")
    def cmd_limits(
        reset: bool = typer.Option(
            False, "--reset", help="Libera o cooldown do circuit breaker"
        ),
        clear_counts: bool = typer.Option(
            False, "--clear-counts", help="Zera os contadores de uso (use com cuidado)"
        ),
    ):
        """Mostra as quotas de hoje/semana e o estado do circuit breaker."""
        limiter = RateLimiter()

        if reset:
            limiter.clear_cooldown()
            console.print("[green]Cooldown liberado.[/green] Runs agendados voltam.")
        if clear_counts:
            limiter._data["counts"] = {}
            limiter._save()
            console.print("[yellow]Contadores zerados.[/yellow]")

        cooldown = limiter.cooldown_reason()
        if cooldown:
            console.print(f"[red]🚫 Em cooldown:[/red] {cooldown}")
            console.print("[dim]Libere com: config limits --reset[/dim]")
        else:
            console.print("[green]✅ Sem cooldown ativo.[/green]")

        janela = "dentro" if within_active_hours() else "[red]fora[/red]"
        console.print(f"Janela de atividade: {janela} do horário permitido.\n")

        table = Table(title="Quotas")
        table.add_column("Ação")
        table.add_column("Hoje", justify="right")
        table.add_column("Semana", justify="right")
        table.add_column("Restam hoje", justify="right")
        table.add_column("Pode agir?")

        for action in DEFAULT_QUOTAS:
            quota = limiter.quota(action)
            status = limiter.check(action)
            verdict = check_run(action, limiter=limiter)
            table.add_row(
                action,
                f"{status.used_today}/{quota.per_day or '∞'}",
                f"{status.used_week}/{quota.per_week or '∞'}",
                str(limiter.remaining_today(action)),
                "[green]sim[/green]" if verdict else f"[red]{verdict.reason}[/red]",
            )
        console.print(table)
        console.print(
            "[dim]Tetos ajustáveis por env: LIMIT_CONNECT_DAY, LIMIT_APPLY_WEEK, …[/dim]"
        )
