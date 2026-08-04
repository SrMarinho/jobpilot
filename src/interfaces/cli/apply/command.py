from typing import Optional, List

import typer

from src.automation.tasks.job_application_manager import create_application_manager
from src.interfaces.cli.browser import run_browser_task
from src.interfaces.cli.enums import DatePosted, WorkplaceType, ExperienceLevel
from src.interfaces.cli.apply.logic import prepare_apply_config


def register_apply_command(app: typer.Typer) -> None:
    @app.command(
        epilog="Parameters are saved per site and restored automatically on next run."
    )
    def apply(
        ctx: typer.Context,
        url: Optional[str] = typer.Option(
            None,
            "--url",
            "-u",
            help="Full search URL (overrides --keywords, saved for later)",
        ),
        keywords: Optional[List[str]] = typer.Option(
            None,
            "--keywords",
            "-k",
            help="Search keywords (repeat: --keyword python --keyword node)",
        ),
        date_posted: Optional[DatePosted] = typer.Option(
            None, "--date-posted", help="Filter by posting date"
        ),
        workplace: Optional[WorkplaceType] = typer.Option(
            None, "--workplace", help="Workplace type filter"
        ),
        location: Optional[str] = typer.Option(
            None, "--location", help="Location filter (e.g. 'Brasil', 'Sao Paulo')"
        ),
        experience: Optional[ExperienceLevel] = typer.Option(
            None, "--experience", help="Experience level filter"
        ),
        resume: Optional[str] = typer.Option(
            None,
            "--resume",
            "-r",
            help="Path to resume PDF or TXT (default: resume.txt)",
        ),
        preferences: Optional[str] = typer.Option(
            None, "--preferences", "-p", help="Preferences to guide evaluation"
        ),
        level: Optional[List[str]] = typer.Option(
            None,
            "--level",
            "-l",
            help="Accepted seniority levels (repeat: --level junior --level pleno)",
        ),
        start_page: Optional[int] = typer.Option(
            None, "--start-page", help="Page to start from (default: 1)"
        ),
        max_pages: int = typer.Option(
            100, "--max-pages", help="Max pages to process (default: 100)"
        ),
        max_applications: int = typer.Option(
            0,
            "--max-applications",
            metavar="N",
            help="Stop after N applications (default: 0 = unlimited)",
        ),
        resume_from: bool = typer.Option(
            False, "--continue", help="Resume from the last page where it stopped"
        ),
        site_name: Optional[str] = typer.Option(
            None,
            "--site",
            help="Resume saved config for a specific site: linkedin, glassdoor, indeed",
        ),
        llm_provider: Optional[str] = typer.Option(
            None,
            "--llm-provider",
            help="Override LLM provider for this run: claude or langchain",
        ),
        llm_model: Optional[str] = typer.Option(
            None, "--llm-model", help="Override LLM model for this run"
        ),
        eval_provider: Optional[str] = typer.Option(
            None,
            "--eval-provider",
            help="Override eval provider for this run: claude or langchain",
        ),
        eval_model: Optional[str] = typer.Option(
            None, "--eval-model", help="Override eval model for this run"
        ),
        no_save: bool = typer.Option(
            False,
            "--no-save",
            help="Run without overwriting the saved URL/config for this site",
        ),
        no_submit: bool = typer.Option(
            False, "--no-submit", help="Fill forms but do not submit (for testing)"
        ),
        eval_concurrency: int = typer.Option(
            1,
            "--eval-concurrency",
            min=1,
            help="Concurrent eval calls (1=sequential, max=site PAGE_SIZE)",
        ),
        eval_batch_size: int = typer.Option(
            1,
            "--eval-batch-size",
            min=1,
            help="Jobs per LLM eval call — batch saves ~50% tokens (resume sent once per batch)",
        ),
        tui: bool = typer.Option(
            False, "--tui", help="Show live Rich TUI panel of pipeline state"
        ),
        easy_apply_only: bool = typer.Option(
            False,
            "--easy-apply-only",
            help="Only apply to Easy Apply jobs (restrict search to candidatura simplificada)",
        ),
    ):
        """Apply to jobs (LinkedIn, Glassdoor, Indeed). By default includes all job types."""

        cfg = prepare_apply_config(
            url,
            keywords,
            date_posted.value
            if date_posted and date_posted != DatePosted.any_
            else None,
            workplace.value if workplace else None,
            location,
            experience.value if experience else None,
            resume,
            preferences,
            level,
            site_name,
            resume_from,
            llm_provider,
            llm_model,
            eval_provider,
            eval_model,
            no_save,
            easy_apply_only,
        )

        async def _work(page):
            if tui:
                from src.utils.tui import JobPipelineApp

                def mf(on_update):
                    return create_application_manager(
                        page,
                        url=cfg["url"],
                        resume_path=cfg["resume_path"],
                        preferences=cfg["preferences"],
                        level=cfg["level"],
                        max_pages=max_pages,
                        max_applications=max_applications,
                        start_page=cfg["start_page"]
                        if resume_from
                        else (start_page or 1),
                        on_page_change=cfg["on_page_change"],
                        no_submit=no_submit,
                        eval_concurrency=eval_concurrency,
                        eval_batch_size=eval_batch_size,
                        on_update=on_update,
                    )

                tui_app = JobPipelineApp(mf)
                await tui_app.run_async()
            else:
                manager = create_application_manager(
                    page,
                    url=cfg["url"],
                    resume_path=cfg["resume_path"],
                    preferences=cfg["preferences"],
                    level=cfg["level"],
                    max_pages=max_pages,
                    max_applications=max_applications,
                    start_page=cfg["start_page"] if resume_from else (start_page or 1),
                    on_page_change=cfg["on_page_change"],
                    no_submit=no_submit,
                    eval_concurrency=eval_concurrency,
                    eval_batch_size=eval_batch_size,
                )
                await manager.run()

        run_browser_task(ctx, "apply", _work)
