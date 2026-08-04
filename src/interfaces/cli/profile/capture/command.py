import typer

from src.utils.async_utils import run_async
from src.utils.logger import set_run_context
from src.interfaces.cli.browser import run_browser
from src.interfaces.cli.engage.logic import capture_metrics


def register_profile_capture_command(app: typer.Typer) -> None:
    @app.command("capture")
    def cmd_capture(
        ctx: typer.Context,
        force: bool = typer.Option(
            False, "--force", help="Recaptura mesmo se já capturou hoje"
        ),
        ssi: bool = typer.Option(False, "--ssi", help="Captura apenas SSI"),
        views: bool = typer.Option(
            False, "--views", help="Captura apenas profile views"
        ),
        appearances: bool = typer.Option(
            False, "--appearances", help="Captura apenas aparições em pesquisa"
        ),
    ):
        """Captura métricas do perfil (SSI, views, aparições). Sem flags = todas."""
        set_run_context("profile-capture")
        headless = ctx.obj.get("headless", False)

        selected = frozenset(
            m
            for m, flag in [
                ("ssi", ssi),
                ("views", views),
                ("appearances", appearances),
            ]
            if flag
        )
        targets = selected if selected else None  # None = todas

        async def _work(page):
            await capture_metrics(page, force=force, targets=targets)

        run_async(run_browser(_work, headless=headless))
