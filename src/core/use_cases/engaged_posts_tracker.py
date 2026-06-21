import json
from collections import Counter
from datetime import datetime, date
from pathlib import Path

from src.config.settings import logger
from src.core.persistence.db import is_db_enabled
from src.core.persistence.doc_repo import DocRepo
from src.core.persistence.keyed_repo import KeyedRepo

_FILES_DIR = Path(".local") / "files"
ENGAGED_POSTS_FILE = _FILES_DIR / "engaged_posts.json"

_HARD_CAP = 500


class EngagedPostsTracker:
    def __init__(self, path: Path = ENGAGED_POSTS_FILE):
        self._path = path
        self._repo = KeyedRepo("engaged_posts", "urn")
        self._meta = DocRepo("engaged_meta")  # self_author (db mode)
        self._data: dict = self._load()
        self._data.setdefault("engaged", [])

    def _load(self) -> dict:
        if is_db_enabled():
            engaged = sorted(self._repo.all(), key=lambda r: r.get("ts") or "")
            data = {"engaged": engaged}
            author = self._meta.load().get("self_author")
            if author:
                data["self_author"] = author
            return data
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning(f"Could not parse {self._path}, starting fresh")
        return {}

    def _save(self):
        _FILES_DIR.mkdir(exist_ok=True, parents=True)
        engaged = self._data.get("engaged", [])
        if len(engaged) > _HARD_CAP:
            self._data["engaged"] = engaged[-_HARD_CAP:]
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self._path)

    def self_author(self, name: str | None = None) -> str | None:
        if name is not None:
            self._data["self_author"] = name
            if is_db_enabled():
                self._meta.save({"self_author": name})
            else:
                self._save()
        return self._data.get("self_author")

    def already_engaged(self, urn: str) -> bool:
        return any(p.get("urn") == urn for p in self._data["engaged"])

    def mark_engaged(
        self,
        urn: str,
        author: str,
        actions: list[str],
        comment: str = "",
        variant: str = "",
    ):
        now = datetime.now()
        record = {
            "urn": urn,
            "ts": now.isoformat(),
            "author": author,
            "actions": actions,
            "comment": comment,
            "variant": variant,
            "month": now.strftime("%Y-%m"),
            "week": now.strftime("%Y-W%W"),
            "day": now.date().isoformat(),
        }
        self._data["engaged"].append(record)
        if is_db_enabled():
            self._repo.upsert(record)
        else:
            self._save()

    def counts_for_week(self, week_key: str) -> dict:
        likes = comments = shares = 0
        authors: list[str] = []
        for p in self._data["engaged"]:
            if p.get("week") != week_key:
                continue
            acts = p.get("actions") or []
            if "like" in acts:
                likes += 1
            if "comment" in acts:
                comments += 1
            if "share" in acts:
                shares += 1
            authors.append(p.get("author", "unknown"))
        return {
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "top_authors": Counter(authors).most_common(5),
        }

    def counts_for_month(self, month_key: str) -> dict:
        likes = comments = shares = 0
        authors: list[str] = []
        for p in self._data["engaged"]:
            if p.get("month") != month_key:
                continue
            acts = p.get("actions") or []
            if "like" in acts:
                likes += 1
            if "comment" in acts:
                comments += 1
            if "share" in acts:
                shares += 1
            authors.append(p.get("author", "unknown"))
        return {
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "top_authors": Counter(authors).most_common(5),
        }

    def today_count(self) -> int:
        today = date.today().isoformat()
        return sum(1 for p in self._data["engaged"] if p.get("day") == today)
