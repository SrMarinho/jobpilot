"""Persistence for autopost — published posts + pending drafts.

Mirrors ``EngagedPostsTracker``: atomic JSON writes, weekly counters,
hard cap. Every generated draft is recorded with a ``status`` so the
weekly report can compute an approval rate; published posts also land in
``posts`` with their URL.
"""

import uuid
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from src.config.settings import logger
from src.core.persistence.doc_repo import DocRepo

_FILES_DIR = Path(".local") / "files"
POSTED_HISTORY_FILE = _FILES_DIR / "posted_history.json"

_HARD_CAP = 300

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"  # aprovado, aguardando publicação
STATUS_REJECTED = "rejected"
STATUS_EXPIRED = "expired"
STATUS_POSTED = "posted"  # já publicado no LinkedIn


class PostedTracker:
    def __init__(self, path: Path = POSTED_HISTORY_FILE):
        self._path = path
        self._doc = DocRepo("posted_history", json_file=path)
        self._data: dict = self._doc.load()
        self._data.setdefault("drafts", [])
        self._data.setdefault("posts", [])

    def _save(self):
        for key in ("drafts", "posts"):
            lst = self._data.get(key, [])
            if len(lst) > _HARD_CAP:
                self._data[key] = lst[-_HARD_CAP:]
        self._doc.save(self._data)

    # ── Drafts ────────────────────────────────────────────────────────────────

    def add_draft(
        self,
        content: str,
        source: str,
        fmt: str,
        topic: str,
        telegram_msg_id: int | None = None,
        expires_hours: int = 4,
    ) -> str:
        now = datetime.now()
        draft_id = uuid.uuid4().hex[:12]
        self._data["drafts"].append(
            {
                "id": draft_id,
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=expires_hours)).isoformat(),
                "status": STATUS_PENDING,
                "source": source,
                "format": fmt,
                "topic": topic,
                "content": content,
                "chars": len(content),
                "telegram_msg_id": telegram_msg_id,
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
            draft["chars"] = len(content)
            self._save()
        return draft

    def pending_drafts(self) -> list[dict]:
        return [d for d in self._data["drafts"] if d.get("status") == STATUS_PENDING]

    def approved_drafts(self) -> list[dict]:
        """Drafts aprovados aguardando publicação (não publicados ainda)."""
        return [d for d in self._data["drafts"] if d.get("status") == STATUS_APPROVED]

    def recent_topics(self, days: int = 30) -> set[str]:
        """Tópicos (normalizados) de drafts+posts dentro da janela ``days``."""
        cutoff = datetime.now() - timedelta(days=days)
        topics: set[str] = set()
        for item, ts_key in (
            *((d, "created_at") for d in self._data["drafts"]),
            *((p, "ts") for p in self._data["posts"]),
        ):
            topic = (item.get("topic") or "").strip().lower()
            if not topic:
                continue
            try:
                ts = datetime.fromisoformat(item.get(ts_key, ""))
            except ValueError:
                continue
            if ts >= cutoff:
                topics.add(topic)
        return topics

    def expire_stale(self) -> int:
        now = datetime.now()
        n = 0
        for d in self._data["drafts"]:
            if d.get("status") != STATUS_PENDING:
                continue
            try:
                exp = datetime.fromisoformat(d.get("expires_at", ""))
            except ValueError:
                continue
            if now > exp:
                d["status"] = STATUS_EXPIRED
                n += 1
        if n:
            self._save()
            logger.info(f"Expirados {n} drafts pendentes")
        return n

    # ── Published posts ───────────────────────────────────────────────────────

    def mark_posted(
        self,
        content: str,
        source: str,
        fmt: str,
        topic: str,
        url: str = "",
        draft_id: str | None = None,
    ) -> None:
        now = datetime.now()
        self._data["posts"].append(
            {
                "id": uuid.uuid4().hex[:12],
                "ts": now.isoformat(),
                "source": source,
                "format": fmt,
                "topic": topic,
                "content": content,
                "url": url,
                "week": now.strftime("%Y-W%W"),
                "month": now.strftime("%Y-%m"),
                "day": now.date().isoformat(),
            }
        )
        if draft_id:
            self.set_status(draft_id, STATUS_POSTED)  # also saves
        else:
            self._save()

    # ── Aggregations ──────────────────────────────────────────────────────────

    def counts_for_week(self, week_key: str) -> dict:
        posts = [p for p in self._data["posts"] if p.get("week") == week_key]
        drafts = [d for d in self._data["drafts"] if d.get("week") == week_key]
        status_counts = Counter(d.get("status") for d in drafts)
        chars = [p.get("chars") or len(p.get("content", "")) for p in posts]
        return {
            "published": len(posts),
            "by_source": dict(Counter(p.get("source", "?") for p in posts)),
            "by_format": dict(Counter(p.get("format", "?") for p in posts)),
            "generated": len(drafts),
            "approved": status_counts.get(STATUS_APPROVED, 0),
            "rejected": status_counts.get(STATUS_REJECTED, 0),
            "expired": status_counts.get(STATUS_EXPIRED, 0),
            "avg_chars": int(sum(chars) / len(chars)) if chars else 0,
        }
