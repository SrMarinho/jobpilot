import os
from typing import Optional

from src.config.settings import logger
from src.core.ai.llm_provider import get_eval_provider
from src.core.ai.warmup import warmup_llm_providers
from src.automation.tasks.autopost_manager import AutopostManager
from src.core.use_cases.posted_tracker import PostedTracker
from src.interfaces.cli.persistence import (
    _find_resume,
    is_already_ran_today,
    save_ran_today,
)


def resolve_autopost_config(
    source: Optional[str],
    topic: Optional[str],
    fmt: Optional[str],
    dry_run: bool,
    no_telegram: bool,
    scheduled: bool,
    force: bool,
) -> dict | None:
    """Returns config dict or None if scheduled run should skip."""
    if scheduled and not force:
        if is_already_ran_today("autopost"):
            logger.info("Autopost já rodou hoje. Skipping (exit 0).")
            return None

    resume_path = _find_resume("")
    os.environ.setdefault("LLM_PROVIDER_EVAL", "langchain")
    warmup_llm_providers()

    if scheduled and not force:
        save_ran_today("autopost")

    return {
        "resume_path": resume_path,
        "source": source,
        "topic": topic,
        "format": fmt,
        "dry_run": dry_run,
        "no_telegram": no_telegram,
        "user_name": os.getenv("USER_NAME", "Matheus Marinho"),
        "user_headline": os.getenv(
            "USER_HEADLINE", "Software Engineer focado em Python e Node.js"
        ),
    }


def _approval_buttons(draft_id: str) -> list:
    return [
        [
            {"text": "✅ Aprovar", "data": f"autopost_approve:{draft_id}"},
            {"text": "❌ Rejeitar", "data": f"autopost_reject:{draft_id}"},
        ],
        [
            {"text": "✏️ Editar", "data": f"autopost_edit:{draft_id}"},
            {"text": "🔄 Regenerar", "data": f"autopost_regen:{draft_id}"},
        ],
    ]


async def run_autopost(cfg: dict) -> None:
    """Generate a draft and route it (print / dry-run preview / approval)."""
    os.environ.setdefault("LLM_PROVIDER_EVAL", "langchain")
    provider = get_eval_provider()
    logger.info(f"Using LLM for autopost: {provider.describe()}")

    tracker = PostedTracker()
    tracker.expire_stale()

    manager = AutopostManager(
        provider,
        resume_path=cfg["resume_path"],
        user_name=cfg["user_name"],
        user_headline=cfg["user_headline"],
        source=cfg["source"],
        topic=cfg["topic"],
        fmt=cfg["format"],
    )
    draft = await manager.generate()
    if not draft:
        logger.warning("Autopost: sem draft para enviar")
        try:
            from src.utils.telegram import send_telegram

            send_telegram("⚠️ <b>Autopost</b>: não consegui gerar um draft válido.")
        except Exception:
            pass
        return

    header = (
        f"📝 <b>Autopost draft</b>\n"
        f"<i>source={draft['source']} · format={draft['format']} · "
        f"{len(draft['content'])} chars</i>\n"
        f"<b>{draft['topic']}</b>\n\n"
    )
    body = draft["content"]

    if cfg["no_telegram"]:
        print("\n===== AUTOPOST DRAFT =====")
        print(
            f"source={draft['source']} format={draft['format']} topic={draft['topic']}"
        )
        print("-" * 40)
        print(body)
        print("=" * 26)
        return

    if cfg["dry_run"]:
        try:
            from src.utils.telegram import send_telegram

            send_telegram(header + body + "\n\n<i>(dry-run — não será publicado)</i>")
        except Exception as e:
            logger.warning(f"dry-run telegram send failed: {e}")
        return

    # Default: record pending draft + send for human approval.
    draft_id = tracker.add_draft(
        content=draft["content"],
        source=draft["source"],
        fmt=draft["format"],
        topic=draft["topic"],
    )
    try:
        from src.utils.telegram import send_telegram_buttons

        send_telegram_buttons(header + body, _approval_buttons(draft_id))
        logger.info(f"Draft {draft_id} enviado para aprovação no Telegram")
    except Exception as e:
        logger.warning(f"Falha ao enviar draft para aprovação: {e}")
