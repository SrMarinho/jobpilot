import typer

from src.utils.logger import set_run_context


def register_dashboard_command(app: typer.Typer) -> None:
    @app.command()
    def dashboard():
        """Dashboard TUI ao vivo (candidaturas, engagement, SSI, metas)."""
        set_run_context("dashboard")
        from src.interfaces.tui.dashboard import run_dashboard

        run_dashboard()
