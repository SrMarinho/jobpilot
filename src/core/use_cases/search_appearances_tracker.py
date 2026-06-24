import json
from datetime import date, datetime
from pathlib import Path

from src.config.settings import logger
from src.core.persistence.db import is_db_enabled
from src.core.persistence.keyed_repo import KeyedRepo

_FILES_DIR = Path(".local") / "files"
SEARCH_APPEARANCES_FILE = _FILES_DIR / "search_appearances.json"


class SearchAppearancesTracker:
    """Snapshot diário de "aparições em pesquisas" (janela rolante ~1 semana).

    Guarda histórico (1 snapshot/dia) p/ analisar tendência: o valor é rolante,
    então comparamos o último com o anterior pra dizer se subiu/caiu.
    """

    def __init__(self, path: Path = SEARCH_APPEARANCES_FILE):
        self._path = path
        self._repo = KeyedRepo("search_appearances", "date")
        self._data: dict = self._load()
        self._data.setdefault("snapshots", [])

    def _load(self) -> dict:
        if is_db_enabled():
            rows = sorted(self._repo.all(), key=lambda r: r.get("date", ""))
            return {"snapshots": rows}
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

    def already_captured_today(self) -> bool:
        today = date.today().isoformat()
        return any(s.get("date") == today for s in self._data["snapshots"])

    def save(self, count: int) -> None:
        """Upsert por dia (1 snapshot/dia, último vence)."""
        now = datetime.now()
        today = now.date().isoformat()
        snap = {"date": today, "count": int(count), "ts": now.isoformat()}
        self._data["snapshots"] = [
            s for s in self._data["snapshots"] if s.get("date") != today
        ]
        self._data["snapshots"].append(snap)
        self._data["snapshots"].sort(key=lambda s: s.get("date", ""))
        if is_db_enabled():
            self._repo.upsert(snap)
        else:
            self._save()

    @property
    def snapshots(self) -> list[dict]:
        return self._data["snapshots"]

    def analyze(self) -> dict:
        """Valor atual, anterior e tendência (sobe/cai/estável)."""
        snaps = sorted(self.snapshots, key=lambda s: s.get("date", ""))
        out: dict = {
            "samples": len(snaps),
            "current": snaps[-1]["count"] if snaps else None,
            "previous": snaps[-2]["count"] if len(snaps) >= 2 else None,
            "trend": "insuficiente",
            "delta": None,
        }
        if len(snaps) >= 2:
            delta = snaps[-1]["count"] - snaps[-2]["count"]
            out["delta"] = delta
            out["trend"] = (
                "subindo" if delta > 0 else "caindo" if delta < 0 else "estável"
            )
        return out
