import os
import json
import asyncio
from typing import Optional, List

import typer
from playwright.async_api import async_playwright

import src.config.settings as setting
from src.utils.logger import set_run_context
from src.config.settings import logger
from src.automation.tasks.job_application_manager import JobApplicationManager, _detect_site
from src.cli.persistence import load_last_urls, save_last_url, LAST_URLS_FILE
from src.cli.browser import _create_context
from src.cli.enums import DatePosted, WorkplaceType, ExperienceLevel
from src.cli.apply_logic import (
    _determine_site_key, _resolve_apply_url_task, _resolve_saved_options,
)


def register_apply_command(app: typer.Typer) -> None:
    @app.command(epilog="Parameters are saved per site and restored automatically on next run.")
    def apply(
        ctx: typer.Context,
        url: Optional[str] = typer.Option(None, "--url", "-u", help="Full search URL (overrides --keywords, saved for later)"),
        keywords: Optional[str] = typer.Option(None, "--keywords", "-k", help="Search keywords (e.g. 'python backend')"),
        date_posted: Optional[DatePosted] = typer.Option(None, "--date-posted", help="Filter by posting date"),
        workplace: Optional[WorkplaceType] = typer.Option(None, "--workplace", help="Workplace type filter"),
        location: Optional[str] = typer.Option(None, "--location", help="Location filter (e.g. 'Brasil', 'Sao Paulo')"),
        experience: Optional[ExperienceLevel] = typer.Option(None, "--experience", help="Experience level filter"),
        resume: Optional[str] = typer.Option(None, "--resume", "-r", help="Path to resume PDF or TXT (default: resume.txt)"),
        preferences: Optional[str] = typer.Option(None, "--preferences", "-p", help="Preferences to guide evaluation"),
        level: Optional[List[str]] = typer.Option(None, "--level", "-l", help="Accepted seniority levels (repeat: --level junior --level pleno)"),
        start_page: Optional[int] = typer.Option(None, "--start-page", help="Page to start from (default: 1)"),
        max_pages: int = typer.Option(100, "--max-pages", help="Max pages to process (default: 100)"),
        max_applications: int = typer.Option(0, "--max-applications", metavar="N", help="Stop after N applications (default: 0 = unlimited)"),
        resume_from: bool = typer.Option(False, "--continue", help="Resume from the last page where it stopped"),
        site_name: Optional[str] = typer.Option(None, "--site", help="Resume saved config for a specific site: linkedin, glassdoor, indeed"),
        llm_provider: Optional[str] = typer.Option(None, "--llm-provider", help="Override LLM provider for this run: claude or langchain"),
        llm_model: Optional[str] = typer.Option(None, "--llm-model", help="Override LLM model for this run"),
        eval_provider: Optional[str] = typer.Option(None, "--eval-provider", help="Override eval provider for this run: claude or langchain"),
        eval_model: Optional[str] = typer.Option(None, "--eval-model", help="Override eval model for this run"),
        no_save: bool = typer.Option(False, "--no-save", help="Run without overwriting the saved URL/config for this site"),
        no_submit: bool = typer.Option(False, "--no-submit", help="Fill forms but do not submit (for testing)"),
        eval_concurrency: int = typer.Option(1, "--eval-concurrency", min=1, help="Concurrent eval calls (1=sequential, max=site PAGE_SIZE)"),
        eval_batch_size: int = typer.Option(5, "--eval-batch-size", min=1, help="Jobs per LLM eval call — batch saves ~50% tokens (resume sent once per batch)"),
        tui: bool = typer.Option(False, "--tui", help="Show live Rich TUI panel of pipeline state"),
    ):
        """Apply to jobs via Easy Apply (LinkedIn, Glassdoor, Indeed)."""
        set_run_context("apply")
        headless = ctx.obj.get("headless", False)
        k_date_posted = date_posted.value if date_posted and date_posted != DatePosted.any_ else None
        k_workplace = workplace.value if workplace else None
        k_experience = experience.value if experience else None

        if not url and not keywords:
            site_key_check = _determine_site_key(None, None, site_name)
            saved_check = load_last_urls().get(site_key_check, {})
            if not saved_check.get("url") and not saved_check.get("keywords"):
                print("Error: pass --url or --keywords for the first run.")
                raise typer.Exit()

        resolved_url, resolved_start_page, site_key, resolved_resume, resolved_search = _resolve_apply_url_task(
            url, keywords, k_date_posted, k_workplace, location, k_experience,
            resume_from, site_name, resume,
        )

        last_urls = load_last_urls()
        saved = last_urls.get(site_key, {})

        final_level = level or _resolve_saved_options(saved)[0] or []
        final_preferences = preferences or _resolve_saved_options(saved)[1] or ""
        final_llm_prov = llm_provider or _resolve_saved_options(saved)[2]
        final_llm_mod = llm_model or _resolve_saved_options(saved)[3]
        final_eval_prov = eval_provider or _resolve_saved_options(saved)[4]
        final_eval_mod = eval_model or _resolve_saved_options(saved)[5]

        final_search = resolved_search.copy()
        if keywords:
            final_search["keywords"] = keywords
        if k_date_posted:
            final_search["date_posted"] = k_date_posted
        if k_workplace:
            final_search["workplace"] = k_workplace
        if location:
            final_search["location"] = location
        if k_experience:
            final_search["experience"] = k_experience

        if final_level:
            print(f"Level filter: {final_level}")
        if final_preferences:
            print(f"Preferences: {final_preferences}")
        if final_eval_prov:
            print(f"Eval provider: {final_eval_prov}" + (f" model={final_eval_mod}" if final_eval_mod else ""))

        if final_llm_prov:
            os.environ["LLM_PROVIDER"] = final_llm_prov
            logger.info(f"[override] LLM_PROVIDER={final_llm_prov}")
        if final_llm_mod:
            key = "LANGCHAIN_MODEL" if os.environ.get("LLM_PROVIDER") == "langchain" else "CLAUDE_MODEL"
            os.environ[key] = final_llm_mod
            logger.info(f"[override] {key}={final_llm_mod}")
        if final_eval_prov:
            os.environ["LLM_PROVIDER_EVAL"] = final_eval_prov
            logger.info(f"[override] LLM_PROVIDER_EVAL={final_eval_prov}")
        if final_eval_mod:
            key = "LANGCHAIN_MODEL_EVAL" if os.environ.get("LLM_PROVIDER_EVAL") == "langchain" else "CLAUDE_MODEL"
            os.environ[key] = final_eval_mod
            logger.info(f"[override] {key}={final_eval_mod}")

        from src.core.ai.llm_provider import get_llm_provider, get_eval_provider
        llm_prov_inst = get_llm_provider()
        eval_prov_inst = get_eval_provider()
        logger.info(f"LLM:  {llm_prov_inst.describe()}")
        logger.info(f"EVAL: {eval_prov_inst.describe()}")
        logger.info("Warming up LLM models...")

        async def _warmup():
            async def _try(name: str, prov):
                try:
                    await prov.complete("hi")
                    logger.info(f"Warmup OK: {name}")
                except Exception as e:
                    logger.warning(f"Warmup failed for {name}: {e}")
            await asyncio.gather(
                _try("llm", llm_prov_inst),
                _try("eval", eval_prov_inst),
            )
        asyncio.run(_warmup())
        logger.info("LLM models ready.")

        if not no_save:
            extra = {
                "level": final_level, "preferences": final_preferences, "resume": resolved_resume,
                "llm_provider": final_llm_prov, "llm_model": final_llm_mod,
                "eval_provider": final_eval_prov, "eval_model": final_eval_mod,
            }
            extra.update(final_search)
            if keywords or url:
                save_last_url(site_key, resolved_url, page=1, extra=extra)
                data = load_last_urls()
                if url:
                    data["apply_last_site"] = _detect_site(url)
                else:
                    data["apply_last_site"] = site_key.replace("apply_", "")
                if resume:
                    data["default_resume"] = resume
                with open(LAST_URLS_FILE, "w") as f:
                    json.dump(data, f, indent=2)

        def on_page_change(page: int):
            if no_save:
                return
            extra = {
                "level": final_level, "preferences": final_preferences, "resume": resolved_resume,
                "llm_provider": final_llm_prov, "llm_model": final_llm_mod,
                "eval_provider": final_eval_prov, "eval_model": final_eval_mod,
            }
            extra.update(final_search)
            save_last_url(site_key, resolved_url, page=page, extra=extra)

        async def _run():
            nonlocal resolved_start_page
            async with async_playwright() as pw:
                context, page = await _create_context(pw, force_headless=headless)
                try:
                    if tui:
                        from src.utils.tui import JobPipelineApp
                        def mf(on_update):
                            return JobApplicationManager(
                                page, url=resolved_url, resume_path=resolved_resume,
                                preferences=final_preferences, level=final_level,
                                max_pages=max_pages, max_applications=max_applications,
                                start_page=resolved_start_page if resume_from else (start_page or 1),
                                on_page_change=on_page_change, no_submit=no_submit,
                                eval_concurrency=eval_concurrency, eval_batch_size=eval_batch_size, on_update=on_update,
                            )
                        tui_app = JobPipelineApp(mf)
                        await tui_app.run_async()
                    else:
                        manager = JobApplicationManager(
                            page, url=resolved_url, resume_path=resolved_resume,
                            preferences=final_preferences, level=final_level,
                            max_pages=max_pages, max_applications=max_applications,
                            start_page=resolved_start_page if resume_from else (start_page or 1),
                            on_page_change=on_page_change, no_submit=no_submit,
                            eval_concurrency=eval_concurrency, eval_batch_size=eval_batch_size,
                        )
                        await manager.run()
                    try:
                        await page.screenshot(path=f"{setting.screenshots_path}.png")
                    except Exception:
                        pass
                except Exception as e:
                    logger.critical(f"{str(e)}")
                    try:
                        await page.screenshot(path=f"{setting.screenshots_path}.png")
                    except Exception:
                        pass
                    raise
                finally:
                    try:
                        await context.close()
                    except Exception:
                        pass

        asyncio.run(_run())
