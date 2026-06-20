from typing import List, Optional

import typer

from src.utils.async_utils import run_async
from src.utils.logger import set_run_context
from src.interfaces.cli.browser import run_browser
from src.interfaces.cli.engage.logic import resolve_engage_config, run_engage_browser


def register_engage_command(app: typer.Typer) -> None:
    @app.command()
    def engage(
        ctx: typer.Context,
        max_posts: int = typer.Option(
            3, "--max-posts", help="Max posts to engage per run (default 3)"
        ),
        no_like: bool = typer.Option(False, "--no-like", help="Skip like action"),
        no_comment: bool = typer.Option(
            False, "--no-comment", help="Skip comment action"
        ),
        no_share: bool = typer.Option(False, "--no-share", help="Skip share action"),
        resume: Optional[str] = typer.Option(
            None, "--resume", help="Override resume path (default: auto-detected)"
        ),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Log decisions/comments without acting"
        ),
        target: Optional[List[str]] = typer.Option(
            None,
            "--target",
            help="Engaja só posts de empresas/pessoas-alvo (repetível)",
        ),
        save_targets: bool = typer.Option(
            False, "--save-targets", help="Persiste os --target informados"
        ),
        scheduled: bool = typer.Option(
            False, "--scheduled", help="Scheduled mode: skip if already ran today"
        ),
        force: bool = typer.Option(
            False, "--force", help="Ignore skip-today guard (debug)"
        ),
    ):
        """Engage with LinkedIn feed posts (like + comment + share via LLM)."""
        set_run_context("engage")
        headless = ctx.obj.get("headless", False)

        cfg = resolve_engage_config(
            resume=resume,
            max_posts=max_posts,
            enable_like=not no_like,
            enable_comment=not no_comment,
            enable_share=not no_share,
            dry_run=dry_run,
            scheduled=scheduled,
            force=force,
            targets=target,
            save_targets=save_targets,
        )
        if cfg is None:
            return  # skip-today exit 0

        async def _work(page):
            await run_engage_browser(page, cfg)

        run_async(run_browser(_work, headless=headless))
