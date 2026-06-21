"""Log de eventos unificado para observabilidade cross-feature.

Um único log captura sucessos e falhas de todas as features (autopost,
engage, followup, connect, apply, checkpoint), servindo de base para
métricas de funil, taxa e latência sem precisar instrumentar 14 trackers.
Mirror do ``PostedTracker``: DocRepo backend-aware, escrita atômica, hard cap.

Cada evento: ``feature`` (ex: "autopost"), ``event`` (ex: "posted"),
``ok`` (sucesso/falha), ``key`` (id que liga eventos do mesmo item, ex:
draft_id — base p/ latência), ``detail`` (texto livre), + ``ts``/``week``/``day``.
"""

import uuid
from datetime import datetime
from pathlib import Path

from src.config.settings import logger
from src.core.persistence.doc_repo import DocRepo

_FILES_DIR = Path(".local") / "files"
EVENTS_FILE = _FILES_DIR / "events.json"

_HARD_CAP = 5000


class EventsTracker:
    def __init__(self, path: Path = EVENTS_FILE):
        self._doc = DocRepo("events", json_file=path)
        self._data: dict = self._doc.load()
        self._data.setdefault("events", [])

    def _save(self) -> None:
        evs = self._data.get("events", [])
        if len(evs) > _HARD_CAP:
            self._data["events"] = evs[-_HARD_CAP:]
        self._doc.save(self._data)

    def record(
        self,
        feature: str,
        event: str,
        ok: bool = True,
        key: str | None = None,
        detail: str = "",
        **extra,
    ) -> str:
        now = datetime.now()
        rec = {
            "id": uuid.uuid4().hex[:12],
            "ts": now.isoformat(),
            "feature": feature,
            "event": event,
            "ok": ok,
            "key": key,
            "detail": detail,
            "week": now.strftime("%Y-W%W"),
            "day": now.date().isoformat(),
        }
        rec.update(extra)
        self._data["events"].append(rec)
        self._save()
        return rec["id"]

    def all(self) -> list[dict]:
        return list(self._data.get("events", []))


def record_event(
    feature: str,
    event: str,
    ok: bool = True,
    key: str | None = None,
    detail: str = "",
    **extra,
) -> None:
    """Atalho tolerante a falha — nunca quebra o fluxo principal."""
    try:
        EventsTracker().record(feature, event, ok=ok, key=key, detail=detail, **extra)
    except Exception as e:
        logger.debug(f"events record failed: {e}")
