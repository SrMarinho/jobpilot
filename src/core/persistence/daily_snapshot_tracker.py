"""Base dos trackers de snapshot diário (um registro por dia, último vence).

SSI, visualizações de perfil e aparições em pesquisa são a mesma mecânica com
payloads diferentes: ler o histórico do backend ativo (JSON local ou Postgres),
gravar no máximo um snapshot por dia e responder "já capturei hoje?". Isso
estava copiado inteiro em cada tracker — mesmo ``_load``, mesmo ``_save`` com
write atômico, mesmo ``if is_db_enabled()`` na hora de gravar.

Subclasses só declaram tabela, arquivo e como montar o payload do dia.
"""

import json
from abc import ABC, abstractmethod
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.config.settings import files_dir, logger
from src.core.persistence.db import is_db_enabled
from src.core.persistence.keyed_repo import KeyedRepo

DATE_KEY = "date"


class DailySnapshotTracker(ABC):
    """Histórico de snapshots diários, backend-aware (JSON local ou Postgres).

    Contrato pras subclasses: ``table`` (nome da tabela/KeyedRepo) e
    ``build_snapshot`` (payload do dia, sem ``date``/``ts`` — a base preenche).
    """

    #: Nome da tabela no Postgres e do KeyedRepo. Chave primária é sempre ``date``.
    table: str

    def __init__(self, path: Path):
        self._path = path
        self._repo = KeyedRepo(self.table, DATE_KEY)
        self._data: dict = self._load()
        self._data.setdefault("snapshots", [])

    # ── Contrato ─────────────────────────────────────────────────────────────

    @abstractmethod
    def build_snapshot(self, *args: Any, **kwargs: Any) -> dict:
        """Payload do snapshot do dia, sem ``date``/``ts``."""

    # ── Persistência ─────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if is_db_enabled():
            rows = sorted(self._repo.all(), key=lambda r: r.get(DATE_KEY, ""))
            return {"snapshots": rows}
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning(f"Could not parse {self._path}, starting fresh")
        return {}

    def _save(self) -> None:
        """Write atômico: grava no .tmp e só então troca o arquivo real.

        Sem isso, um crash no meio do write deixaria o histórico truncado.
        """
        files_dir.mkdir(exist_ok=True, parents=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self._path)

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Upsert do snapshot de hoje — um por dia, o último vence."""
        now = datetime.now()
        today = now.date().isoformat()
        snapshot = {
            **self.build_snapshot(*args, **kwargs),
            DATE_KEY: today,
            "ts": now.isoformat(),
        }
        self._data["snapshots"] = [
            s for s in self.snapshots if s.get(DATE_KEY) != today
        ] + [snapshot]
        self._data["snapshots"].sort(key=lambda s: s.get(DATE_KEY, ""))
        if is_db_enabled():
            self._repo.upsert(snapshot)
        else:
            self._save()

    # ── Leitura ──────────────────────────────────────────────────────────────

    @property
    def snapshots(self) -> list[dict]:
        return self._data["snapshots"]

    def already_captured_today(self) -> bool:
        today = date.today().isoformat()
        return any(s.get(DATE_KEY) == today for s in self.snapshots)

    @staticmethod
    def snapshot_date(snapshot: dict) -> date | None:
        """Data do snapshot, ou ``None`` se ilegível."""
        try:
            return date.fromisoformat(snapshot.get(DATE_KEY, ""))
        except Exception:
            return None

    def sorted_snapshots(self) -> list[dict]:
        """Snapshots com data válida, em ordem cronológica."""
        return sorted(
            (s for s in self.snapshots if self.snapshot_date(s) is not None),
            key=lambda s: s[DATE_KEY],
        )
