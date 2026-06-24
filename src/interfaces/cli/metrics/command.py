import typer

from src.utils.async_utils import run_async
from src.utils.logger import set_run_context
from src.interfaces.cli.browser import run_browser
from src.interfaces.cli.engage.logic import capture_metrics


def register_metrics_command(app: typer.Typer) -> None:
    @app.command()
    def metrics(
        ctx: typer.Context,
        force: bool = typer.Option(
            False, "--force", help="Recaptura mesmo se já capturado hoje"
        ),
    ):
        """Atualiza só as métricas do perfil (SSI + profile-views 90d), sem engajar."""
        set_run_context("metrics")
        headless = ctx.obj.get("headless", False)

        async def _work(page):
            await capture_metrics(page, force=force)

        run_async(run_browser(_work, headless=headless))
