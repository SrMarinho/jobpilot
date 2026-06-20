from typing import Optional, List

import typer

from src.utils.async_utils import run_async
from src.utils.logger import set_run_context
from src.interfaces.cli.browser import run_browser
from src.interfaces.cli.enums import NetworkDegree
from src.interfaces.cli.connect.logic import resolve_connect_config, run_connect_browser


def register_connect_command(app: typer.Typer) -> None:
    @app.command()
    def connect(
        ctx: typer.Context,
        url: Optional[str] = typer.Option(
            None,
            "--url",
            "-u",
            help="Full LinkedIn people search URL (overrides --keywords)",
        ),
        keywords: Optional[List[str]] = typer.Option(
            None,
            "--keywords",
            "-k",
            help="Search keywords (repeat: --keyword tech --keyword recruiter)",
        ),
        network: Optional[NetworkDegree] = typer.Option(
            None, "--network", help="Connection degree filter (F=1st, S=2nd, O=3rd+)"
        ),
        start_page: Optional[int] = typer.Option(
            None, "--start-page", help="Page to start from (default: 1)"
        ),
        max_pages: int = typer.Option(
            100, "--max-pages", help="Max pages to process (default: 100)"
        ),
        resume: bool = typer.Option(
            False, "--continue", help="Resume from the last page where it stopped"
        ),
        scheduled: bool = typer.Option(
            False,
            "--scheduled",
            help="Scheduled mode: skip if already ran today or weekly limit reached",
        ),
        rotate: bool = typer.Option(
            False,
            "--rotate",
            help="Use the next saved-search in rotation (see 'searches' command)",
        ),
    ):
        """Send connection requests (LinkedIn people search)."""
        set_run_context("connect")
        headless = ctx.obj.get("headless", False)

        cfg = resolve_connect_config(
            url,
            keywords,
            network.value if network else None,
            start_page,
            resume,
            scheduled,
            rotate,
        )
        if cfg is None:
            return  # scheduled skip

        async def _work(page):
            await run_connect_browser(
                page,
                cfg["url"],
                max_pages,
                cfg["start_page"],
                cfg["on_page_change"],
            )

        run_async(run_browser(_work, headless=headless))
