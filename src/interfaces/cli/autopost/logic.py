import os
from typing import Optional

from src.config.settings import logger
from src.core.ai.llm_provider import get_eval_provider
from src.core.ai.warmup import warmup_llm_providers
from src.automation.tasks.autopost_manager import AutopostManager
from src.core.use_cases.posted_tracker import PostedTracker, STATUS_APPROVED
from src.interfaces.cli.persistence import (
    _find_resume,
    is_already_ran_today,
    save_ran_today,
)


def _notify(text: str) -> None:
    try:
        from src.utils.telegram import send_telegram

        send_telegram(text, topic="autopost")
    except Exception:
        pass


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


def list_drafts() -> None:
    """Lista drafts pendentes + aprovados com seus ids (gestão via CLI)."""
    tracker = PostedTracker()
    tracker.expire_stale()
    pend = tracker.pending_drafts()
    appr = tracker.approved_drafts()
    print("\n===== AUTOPOST DRAFTS =====")
    print(f"Pendentes ({len(pend)}):")
    for d in pend:
        print(
            f"  [{d['id']}] {d.get('topic', '?')}  (expira {d.get('expires_at', '?')})"
        )
    print(f"Aprovados aguardando publicação ({len(appr)}):")
    for d in appr:
        print(f"  [{d['id']}] {d.get('topic', '?')}")
    print("===========================")


def approve_draft(draft_id: str) -> None:
    """Aprova um draft via CLI (será publicado no próximo --publish-approved)."""
    tracker = PostedTracker()
    draft = tracker.get_draft(draft_id)
    if not draft:
        print(f"[ERRO] Draft {draft_id} nao encontrado.")
        return
    status = draft.get("status")
    if status != "pending":
        print(f"[ERRO] Draft {draft_id} esta '{status}', so da para aprovar pendente.")
        return
    tracker.set_status(draft_id, STATUS_APPROVED)
    from src.core.use_cases.events_tracker import record_event

    record_event("autopost", "approved", key=draft_id, detail="cli")
    print(
        f"[OK] Draft {draft_id} aprovado. Publica no proximo 'autopost --publish-approved'."
    )


async def run_publish_approved() -> None:
    """Drena aprovações do Telegram e publica os drafts aprovados (sem bot)."""
    from src.core.use_cases.autopost_approvals import drain_autopost_approvals
    from src.automation.tasks.autopost_publisher import publish_content
    from src.core.use_cases.events_tracker import record_event

    drain_autopost_approvals()

    tracker = PostedTracker()
    tracker.expire_stale()
    approved = tracker.approved_drafts()
    if not approved:
        logger.info("Autopost: nenhum draft aprovado para publicar")
        return

    logger.info(f"Autopost: publicando {len(approved)} draft(s) aprovado(s)")
    for draft in approved:
        logger.info(f"Publicando draft {draft['id']} (topic={draft.get('topic')!r})")
        try:
            ok, url = await publish_content(draft["content"])
        except Exception as e:
            logger.error(f"Erro ao publicar draft {draft['id']}: {e}")
            _notify(f"❌ <b>Autopost</b>: erro ao publicar draft aprovado: {e}")
            continue
        if ok:
            tracker.mark_posted(
                draft["content"],
                draft["source"],
                draft["format"],
                draft["topic"],
                url=url,
                draft_id=draft["id"],
            )
            record_event("autopost", "posted", key=draft["id"], detail=url or "")
            _notify(f"✅ <b>Autopost</b>: post publicado!\n{url}".strip())
        else:
            # falha já registrada com o passo exato por _alert no composer
            _notify("❌ <b>Autopost</b>: falha ao publicar draft aprovado.")


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
        recent=tracker.recent_topics(days=30),
    )
    draft = await manager.generate()
    if not draft:
        logger.warning("Autopost: sem draft para enviar")
        try:
            from src.utils.telegram import send_telegram

            send_telegram(
                "⚠️ <b>Autopost</b>: não consegui gerar um draft válido.",
                topic="autopost",
            )
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

            send_telegram(
                header + body + "\n\n<i>(dry-run — não será publicado)</i>",
                topic="autopost",
            )
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
    from src.core.use_cases.events_tracker import record_event

    record_event(
        "autopost",
        "generated",
        key=draft_id,
        detail=draft["source"],
        fmt=draft["format"],
    )
    try:
        from src.utils.telegram import send_telegram_buttons

        send_telegram_buttons(
            header + body, _approval_buttons(draft_id), topic="autopost"
        )
        logger.info(f"Draft {draft_id} enviado para aprovação no Telegram")
    except Exception as e:
        logger.warning(f"Falha ao enviar draft para aprovação: {e}")
