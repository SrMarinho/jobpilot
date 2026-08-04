"""Persistência dos follow-up DMs pós-conexão.

Cada conexão nova vira um draft (status pending) keyed por profile_url; após
aprovação humana e envio vira um registro em ``sent``. Mesmo molde do
``PostedTracker``: save atômico, hard cap, chaves week/month/day, dedupe por
perfil pra nunca mandar dois DMs pra mesma pessoa.
"""

import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

from src.core.persistence.doc_repo import DocRepo
from src.config.settings import files_dir

FOLLOWUP_FILE = files_dir / "followup_dms.json"

_HARD_CAP = 500

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_SENT = "sent"
STATUS_SKIPPED = "skipped"


class FollowupTracker:
    def __init__(self, path: Path = FOLLOWUP_FILE):
        self._path = path
        self._doc = DocRepo("followup_dms", json_file=path)
        self._data: dict = self._doc.load()
        self._data.setdefault("drafts", [])
        self._data.setdefault("sent", [])

    def _save(self):
        for key in ("drafts", "sent"):
            lst = self._data.get(key, [])
            if len(lst) > _HARD_CAP:
                self._data[key] = lst[-_HARD_CAP:]
        self._doc.save(self._data)

    # ── Dedupe ────────────────────────────────────────────────────────────────

    def already_seen(self, profile_url: str) -> bool:
        """True se já há draft ou envio para este perfil (qualquer status)."""
        key = (profile_url or "").rstrip("/")
        if any(
            (d.get("profile_url") or "").rstrip("/") == key
            for d in self._data["drafts"]
        ):
            return True
        return any(
            (s.get("profile_url") or "").rstrip("/") == key for s in self._data["sent"]
        )

    # ── Drafts ────────────────────────────────────────────────────────────────

    def add_draft(
        self, name: str, profile_url: str, headline: str, content: str
    ) -> str:
        now = datetime.now()
        draft_id = uuid.uuid4().hex[:12]
        self._data["drafts"].append(
            {
                "id": draft_id,
                "created_at": now.isoformat(),
                "status": STATUS_PENDING,
                "name": name,
                "profile_url": profile_url,
                "headline": headline,
                "content": content,
                "week": now.strftime("%Y-W%W"),
                "month": now.strftime("%Y-%m"),
                "day": now.date().isoformat(),
            }
        )
        self._save()
        return draft_id

    def get_draft(self, draft_id: str) -> dict | None:
        return next((d for d in self._data["drafts"] if d.get("id") == draft_id), None)

    def set_status(self, draft_id: str, status: str) -> dict | None:
        draft = self.get_draft(draft_id)
        if draft:
            draft["status"] = status
            self._save()
        return draft

    def update_content(self, draft_id: str, content: str) -> dict | None:
        draft = self.get_draft(draft_id)
        if draft:
            draft["content"] = content
            self._save()
        return draft

    def pending_drafts(self) -> list[dict]:
        return [d for d in self._data["drafts"] if d.get("status") == STATUS_PENDING]

    # ── Sent ──────────────────────────────────────────────────────────────────

    def mark_sent(self, draft_id: str) -> dict | None:
        draft = self.get_draft(draft_id)
        if not draft:
            return None
        now = datetime.now()
        self._data["sent"].append(
            {
                "id": uuid.uuid4().hex[:12],
                "ts": now.isoformat(),
                "name": draft.get("name"),
                "profile_url": draft.get("profile_url"),
                "content": draft.get("content"),
                "week": now.strftime("%Y-W%W"),
                "month": now.strftime("%Y-%m"),
                "day": now.date().isoformat(),
            }
        )
        draft["status"] = STATUS_SENT
        self._save()
        return draft

    # ── Aggregations ──────────────────────────────────────────────────────────

    def counts_for_week(self, week_key: str) -> dict:
        sent = [s for s in self._data["sent"] if s.get("week") == week_key]
        drafts = [d for d in self._data["drafts"] if d.get("week") == week_key]
        status = Counter(d.get("status") for d in drafts)
        return {
            "sent": len(sent),
            "generated": len(drafts),
            "approved": status.get(STATUS_APPROVED, 0) + status.get(STATUS_SENT, 0),
            "rejected": status.get(STATUS_REJECTED, 0),
            "skipped": status.get(STATUS_SKIPPED, 0),
        }
