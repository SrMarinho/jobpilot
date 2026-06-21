import json
from datetime import date, datetime
from pathlib import Path

from src.config.settings import logger
from src.core.persistence.db import is_db_enabled
from src.core.persistence.keyed_repo import KeyedRepo

_FILES_DIR = Path(".local") / "files"
PROFILE_VIEWS_FILE = _FILES_DIR / "profile_views.json"


class ProfileViewsTracker:
    """Snapshot diário da contagem de visualizações do perfil (janela 90 dias).

    O valor é um total *rolante* de 90 dias, não cumulativo. Por isso a análise
    olha a 1ª derivada (variação/dia = ritmo) e a 2ª (variação do ritmo =
    aceleração) — responde "está subindo?" E "está acelerando?".
    """

    def __init__(self, path: Path = PROFILE_VIEWS_FILE):
        self._path = path
        self._repo = KeyedRepo("profile_views", "date")
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

    def save(self, views: int) -> None:
        """Upsert por dia (1 snapshot/dia, último vence)."""
        now = datetime.now()
        today = now.date().isoformat()
        snap = {"date": today, "views": int(views), "ts": now.isoformat()}
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

    @staticmethod
    def _snap_date(s: dict) -> date | None:
        try:
            return date.fromisoformat(s.get("date", ""))
        except Exception:
            return None

    def _daily_rates(self) -> list[tuple[date, float]]:
        """Variação por dia entre snapshots consecutivos (normaliza buracos)."""
        snaps = sorted(
            (s for s in self.snapshots if self._snap_date(s) is not None),
            key=lambda s: s["date"],
        )
        rates: list[tuple[date, float]] = []
        for prev, cur in zip(snaps, snaps[1:]):
            d0, d1 = self._snap_date(prev), self._snap_date(cur)
            span = (d1 - d0).days or 1
            rate = (cur["views"] - prev["views"]) / span
            rates.append((d1, rate))
        return rates

    def analyze(self, window: int = 7) -> dict:
        """Tendência + aceleração.

        Compara ritmo médio (visitas/dia) da janela recente vs a janela anterior.
        ``accel`` > 0 => acelerando; < 0 => desacelerando.
        """
        snaps = sorted(
            (s for s in self.snapshots if self._snap_date(s) is not None),
            key=lambda s: s["date"],
        )
        out: dict = {
            "samples": len(snaps),
            "current": snaps[-1]["views"] if snaps else None,
            "first": snaps[0]["views"] if snaps else None,
            "trend": "insuficiente",
            "accel": None,
            "rate_recent": None,
            "rate_prior": None,
        }
        rates = self._daily_rates()
        if len(rates) < 2:
            return out

        vals = [r for _, r in rates]
        recent = vals[-window:]
        prior = vals[-2 * window : -window] or vals[: max(1, len(vals) - len(recent))]
        rate_recent = sum(recent) / len(recent)
        rate_prior = sum(prior) / len(prior) if prior else rate_recent
        accel = rate_recent - rate_prior

        out["rate_recent"] = round(rate_recent, 2)
        out["rate_prior"] = round(rate_prior, 2)
        out["accel"] = round(accel, 2)

        # Tendência (sinal do ritmo recente) + aceleração (sinal da 2ª derivada).
        eps = 0.05
        if rate_recent > eps:
            direction = "subindo"
        elif rate_recent < -eps:
            direction = "caindo"
        else:
            direction = "estável"
        if accel > eps:
            pace = "acelerando"
        elif accel < -eps:
            pace = "desacelerando"
        else:
            pace = "ritmo constante"
        out["trend"] = direction
        out["pace"] = pace
        return out
