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
    count: int = 1,
    expires_hours: int = 0,
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
        "count": max(1, int(count or 1)),
        "expires_hours": int(expires_hours or 0),
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
            ok, url = await publish_content(draft["content"], draft.get("image_path"))
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
    """Gera 1+ drafts (batch) e roteia cada um (print / dry-run / aprovação).

    Em batch, faz dedup entre os drafts do próprio run (acumula tópicos vistos)
    além do dedup de 30 dias já existente.
    """
    os.environ.setdefault("LLM_PROVIDER_EVAL", "langchain")
    provider = get_eval_provider()
    logger.info(f"Using LLM for autopost: {provider.describe()}")

    tracker = PostedTracker()
    tracker.expire_stale()

    count = cfg.get("count", 1)
    base_recent = tracker.recent_topics(days=30)
    seen: set[str] = set()
    made = 0

    for i in range(count):
        manager = AutopostManager(
            provider,
            resume_path=cfg["resume_path"],
            user_name=cfg["user_name"],
            user_headline=cfg["user_headline"],
            source=cfg["source"],
            topic=cfg["topic"],
            fmt=cfg["format"],
            recent=base_recent | seen,
        )
        draft = await manager.generate()
        if not draft:
            logger.warning(f"Autopost: sem draft no item {i + 1}/{count}")
            continue
        seen.add((draft.get("topic") or "").strip().lower())
        await _route_draft(draft, cfg, tracker)
        made += 1

    logger.info(f"Autopost batch: {made}/{count} draft(s) gerado(s)")
    if made == 0:
        try:
            from src.utils.telegram import send_telegram

            send_telegram(
                "⚠️ <b>Autopost</b>: não consegui gerar um draft válido.",
                topic="autopost",
            )
        except Exception:
            pass


async def _route_draft(draft: dict, cfg: dict, tracker) -> None:
    """Roteia um draft: stdout (no_telegram) / preview (dry_run) / aprovação."""
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
        caption = header + body + "\n\n<i>(dry-run — não será publicado)</i>"
        image_path = await _render_draft_card(draft, "dryrun")
        try:
            from src.utils.telegram import send_telegram, send_telegram_photo

            if image_path:
                send_telegram_photo(image_path, caption, topic="autopost")
            else:
                send_telegram(caption, topic="autopost")
        except Exception as e:
            logger.warning(f"dry-run telegram send failed: {e}")
        return

    # Default: record pending draft + send for human approval.
    draft_id = tracker.add_draft(
        content=draft["content"],
        source=draft["source"],
        fmt=draft["format"],
        topic=draft["topic"],
        expires_hours=cfg.get("expires_hours") or None,  # 0/None = sem expirar
    )
    from src.core.use_cases.events_tracker import record_event

    record_event(
        "autopost",
        "generated",
        key=draft_id,
        detail=draft["source"],
        fmt=draft["format"],
    )

    # Card de imagem (best-effort): gera PNG on-brand do tópico e anexa ao draft.
    image_path = await _render_draft_card(draft, draft_id)
    if image_path:
        tracker.set_image(draft_id, image_path)

    try:
        from src.utils.telegram import (
            send_telegram_buttons,
            send_telegram_photo_buttons,
        )

        buttons = _approval_buttons(draft_id)
        if image_path:
            msg_id = send_telegram_photo_buttons(
                image_path, header + body, buttons, topic="autopost"
            )
        else:
            msg_id = send_telegram_buttons(header + body, buttons, topic="autopost")
        # guarda o message_id p/ remover os botões ao aprovar/rejeitar
        if msg_id:
            tracker.set_telegram_msg_id(draft_id, msg_id)
        logger.info(f"Draft {draft_id} enviado para aprovação no Telegram")
    except Exception as e:
        logger.warning(f"Falha ao enviar draft para aprovação: {e}")


async def _render_draft_card(draft: dict, draft_id: str) -> str | None:
    """Renderiza o card PNG do draft. Best-effort: erro não quebra o autopost."""
    try:
        from src.core.use_cases.post_image import derive_card_copy, render_card_png

        copy = derive_card_copy(
            draft.get("topic", ""), draft.get("content", ""), draft.get("format", "")
        )
        out = f".local/files/post_images/{draft_id}.png"
        await render_card_png(
            copy["title"], copy["subtitle"], out, kicker=copy["kicker"]
        )
        return out
    except Exception as e:
        logger.warning(f"Falha ao gerar card do draft {draft_id} (segue sem): {e}")
        return None
