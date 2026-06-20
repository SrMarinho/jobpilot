"""Rotação de saved-searches.

Uma lista de URLs de busca (connect/apply) que roda em rodízio: cada run
agendado pega a próxima da fila, avançando um cursor por tarefa. Mais
cobertura sem repetir sempre a mesma busca. Persistência atômica, mesmo
molde dos outros trackers.
"""

import json
from pathlib import Path

from src.config.settings import logger

_FILES_DIR = Path(".local") / "files"
SAVED_SEARCHES_FILE = _FILES_DIR / "saved_searches.json"


class SavedSearches:
    def __init__(self, path: Path = SAVED_SEARCHES_FILE):
        self._path = path
        self._data: dict = self._load()
        self._data.setdefault("searches", [])
        self._data.setdefault("cursor", {})

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning(f"Could not parse {self._path}, starting fresh")
        return {}

    def _save(self) -> None:
        _FILES_DIR.mkdir(exist_ok=True, parents=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self._path)

    def list(self, task: str | None = None) -> list[dict]:
        items = self._data["searches"]
        if task:
            return [s for s in items if s.get("task") == task]
        return list(items)

    def add(self, label: str, url: str, task: str = "connect") -> dict:
        entry = {"label": label, "url": url, "task": task}
        self._data["searches"].append(entry)
        self._save()
        logger.info(f"Saved search adicionada: {label} ({task})")
        return entry

    def remove(self, index: int) -> dict | None:
        items = self._data["searches"]
        if 0 <= index < len(items):
            removed = items.pop(index)
            self._save()
            return removed
        return None

    def next(self, task: str = "connect") -> dict | None:
        """Return the next search for ``task`` round-robin, advancing the cursor."""
        pool = self.list(task)
        if not pool:
            return None
        cursor = self._data["cursor"]
        idx = cursor.get(task, 0) % len(pool)
        cursor[task] = (idx + 1) % len(pool)
        self._save()
        chosen = pool[idx]
        logger.info(f"Saved search rotação ({task}): '{chosen.get('label')}' [{idx}]")
        return chosen
