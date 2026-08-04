import os
from typing import Optional

from playwright.async_api import Page

from src.config import sections as settings_sections
from src.config.settings import logger
from src.core.ai.llm_provider import get_eval_provider
from src.core.ai.warmup import warmup_llm_providers
from src.automation.tasks.followup_manager import FollowupManager
from src.interfaces.cli.persistence import (
    _find_resume,
    is_already_ran_today,
    save_ran_today,
)


def resolve_followup_config(
    resume: Optional[str],
    max_dms: int,
    scheduled: bool,
    force: bool,
) -> dict | None:
    """Returns config dict or None if scheduled run should skip."""
    if scheduled and not force:
        if is_already_ran_today("followup"):
            logger.info("Follow-up já rodou hoje. Skipping (exit 0).")
            return None

    resume_path = _find_resume(resume or "")
    os.environ.setdefault("LLM_PROVIDER_EVAL", "langchain")
    warmup_llm_providers()

    if scheduled and not force:
        save_ran_today("followup")

    return {
        "resume_path": resume_path,
        "max_dms": max_dms,
        **settings_sections.user.as_dict(),
    }


async def run_followup_browser(page: Page, cfg: dict) -> None:
    provider = get_eval_provider()
    logger.info(f"Using LLM for follow-up: {provider.describe()}")
    manager = FollowupManager(
        page,
        llm_provider=provider,
        resume_path=cfg["resume_path"],
        user_name=cfg["user_name"],
        user_headline=cfg["user_headline"],
        max_dms=cfg["max_dms"],
    )
    await manager.scan()
