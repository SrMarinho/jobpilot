import os
from typing import Optional

from playwright.async_api import Page

from src.config.settings import logger
from src.core.ai.llm_provider import get_eval_provider
from src.core.ai.warmup import warmup_llm_providers
from src.automation.tasks.engagement_manager import EngagementManager
from src.interfaces.cli.persistence import (
    _find_resume,
    is_already_ran_today,
    save_ran_today,
)


def resolve_engage_config(
    resume: Optional[str],
    max_posts: int,
    enable_like: bool,
    enable_comment: bool,
    enable_share: bool,
    dry_run: bool,
    scheduled: bool,
    force: bool,
    targets: list[str] | None = None,
    save_targets: bool = False,
) -> dict | None:
    """Returns config dict or None if scheduled run should skip."""
    if scheduled and not force:
        if is_already_ran_today("engage"):
            logger.info("Engage already ran today. Skipping (exit 0).")
            return None

    resume_path = _find_resume(resume or "")
    if not os.path.exists(resume_path):
        logger.warning(f"Resume not found at {resume_path}, continuing with no context")

    os.environ.setdefault("LLM_PROVIDER_EVAL", "langchain")
    warmup_llm_providers()

    if scheduled and not force:
        save_ran_today("engage")

    # Alvos: usa os --target ou os salvos; persiste se pedido.
    from src.core.use_cases.engage_targets import load_targets, save_targets as _save

    resolved_targets = list(targets) if targets else load_targets()
    if save_targets and targets:
        _save(targets)

    return {
        "resume_path": resume_path,
        "max_posts": max_posts,
        "enable_like": enable_like,
        "enable_comment": enable_comment,
        "enable_share": enable_share,
        "dry_run": dry_run,
        "targets": resolved_targets,
        "user_name": os.getenv("USER_NAME", "Matheus Marinho"),
        "user_headline": os.getenv(
            "USER_HEADLINE", "Software Engineer focado em Python e Node.js"
        ),
    }


async def run_engage_browser(page: Page, cfg: dict) -> None:
    provider = get_eval_provider()
    logger.info(f"Using LLM for engagement: {provider.describe()}")
    manager = EngagementManager(
        page,
        llm_provider=provider,
        resume_path=cfg["resume_path"],
        user_name=cfg["user_name"],
        user_headline=cfg["user_headline"],
        max_posts=cfg["max_posts"],
        enable_like=cfg["enable_like"],
        enable_comment=cfg["enable_comment"],
        enable_share=cfg["enable_share"],
        dry_run=cfg["dry_run"],
        targets=cfg.get("targets") or [],
    )
    result = await manager.run()

    # Capture SSI snapshot (best-effort; never breaks engage). Browser is
    # already logged in. Once per day — skip if already captured today.
    try:
        from src.automation.pages.ssi_page import SSIPage
        from src.core.use_cases.ssi_tracker import SSITracker

        ssi_tracker = SSITracker()
        if ssi_tracker.already_captured_today():
            logger.info("SSI already captured today, skipping")
        else:
            snap = await SSIPage(page).scrape_with_goto()
            if snap:
                ssi_tracker.save(snap)
                logger.info(f"SSI captured: total={snap['total']}/100")
            else:
                logger.warning("SSI scrape returned no data")
    except Exception as e:
        logger.warning(f"SSI capture failed (non-fatal): {e}")

    try:
        from src.utils.telegram import send_telegram

        send_telegram(
            f"🤝 <b>Engagement</b>\n"
            f"❤️ Likes: {result.liked}\n"
            f"💬 Comments: {result.commented}\n"
            f"🔁 Shares: {result.shared}"
        )
    except Exception as e:
        logger.debug(f"Telegram notify failed (non-fatal): {e}")
