"""Drena toques de aprovação do Telegram sem bot persistente (one-shot).

Um run agendado chama :func:`drain_autopost_approvals` para puxar via
``getUpdates`` os botões que o usuário tocou desde o último drain, aplicando
``approved``/``rejected`` no ``posted_history.json``. O ``offset`` do Telegram
é persistido em disco para que runs consecutivos não reprocessem updates.

⚠️ Não rode isto enquanto o bot persistente estiver de pé: ambos consomem o
mesmo stream de ``getUpdates`` e um roubaria updates do outro.
"""

import json
from pathlib import Path

from src.config.settings import logger
from src.core.use_cases.events_tracker import record_event
from src.core.use_cases.posted_tracker import (
    PostedTracker,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
)

_OFFSET_FILE = Path(".local") / "files" / "telegram_offset.json"


def _load_offset() -> int:
    try:
        return int(json.loads(_OFFSET_FILE.read_text()).get("offset", 0))
    except Exception:
        return 0


def _save_offset(offset: int) -> None:
    try:
        _OFFSET_FILE.parent.mkdir(parents=True, exist_ok=True)
        _OFFSET_FILE.write_text(json.dumps({"offset": offset}))
    except Exception as e:
        logger.warning(f"save telegram offset failed: {e}")


def drain_autopost_approvals() -> dict:
    """Lê toques de aprovação pendentes e aplica no tracker.

    Returns counts ``{"approved": n, "rejected": n}``.
    """
    from src.bot.client import TelegramClient

    client = TelegramClient()
    counts = {"approved": 0, "rejected": 0}
    if not client.token:
        logger.info("Telegram não configurado — drain pulado")
        return counts

    client.offset = _load_offset()
    updates = client.get_updates(timeout=0)
    if not updates:
        return counts

    tracker = PostedTracker()
    max_id = client.offset - 1
    for upd in updates:
        max_id = max(max_id, upd.get("update_id", max_id))
        cq = upd.get("callback_query")
        if not cq:
            continue
        action, _, draft_id = cq.get("data", "").partition(":")
        if action not in ("autopost_approve", "autopost_reject"):
            continue
        client.answer_callback(cq.get("id", ""))
        msg = cq.get("message") or {}
        client.edit_reply_markup(msg.get("chat", {}).get("id"), msg.get("message_id"))
        draft = tracker.get_draft(draft_id)
        if not draft or draft.get("status") != STATUS_PENDING:
            continue
        if action == "autopost_approve":
            tracker.set_status(draft_id, STATUS_APPROVED)
            record_event("autopost", "approved", key=draft_id, detail="telegram_drain")
            counts["approved"] += 1
        else:
            tracker.set_status(draft_id, STATUS_REJECTED)
            record_event("autopost", "rejected", key=draft_id, detail="telegram_drain")
            counts["rejected"] += 1

    _save_offset(max_id + 1)
    if counts["approved"] or counts["rejected"]:
        logger.info(f"Drain Telegram autopost: {counts}")
        record_event(
            "autopost",
            "drain",
            approved=counts["approved"],
            rejected=counts["rejected"],
        )
    return counts
