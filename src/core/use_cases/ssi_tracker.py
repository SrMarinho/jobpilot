import json
from datetime import datetime, date, timedelta
from pathlib import Path

from src.config.settings import logger

_FILES_DIR = Path(".local") / "files"
SSI_HISTORY_FILE = _FILES_DIR / "ssi_history.json"


def _week_range(year: int, week: int) -> tuple[date, date]:
    """Monday-Sunday range matching date.strftime('%W'). Mirrors weekly_report."""
    jan1 = date(year, 1, 1)
    days_to_monday = (7 - jan1.weekday()) % 7
    first_monday = jan1 + timedelta(days=days_to_monday)
    start = first_monday + timedelta(weeks=week - 1)
    end = start + timedelta(days=6)
    return start, end


class SSITracker:
    def __init__(self, path: Path = SSI_HISTORY_FILE):
        self._path = path
        self._data: dict = self._load()
        self._data.setdefault("snapshots", [])

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

    def already_captured_today(self) -> bool:
        today = date.today().isoformat()
        return any(s.get("date") == today for s in self._data["snapshots"])

    def save(self, snapshot: dict) -> None:
        """Upsert by date (one snapshot per day, latest wins)."""
        now = datetime.now()
        today = now.date().isoformat()
        snapshot = {**snapshot, "date": today, "ts": now.isoformat()}
        self._data["snapshots"] = [
            s for s in self._data["snapshots"] if s.get("date") != today
        ]
        self._data["snapshots"].append(snapshot)
        self._data["snapshots"].sort(key=lambda s: s.get("date", ""))
        self._save()

    @staticmethod
    def _snap_date(s: dict) -> date | None:
        try:
            return date.fromisoformat(s.get("date", ""))
        except Exception:
            return None

    def latest_in_week(self, year: int, week: int) -> dict | None:
        start, end = _week_range(year, week)
        in_week = [
            s
            for s in self._data["snapshots"]
            if (d := self._snap_date(s)) and start <= d <= end
        ]
        return in_week[-1] if in_week else None

    def latest_before_week(self, year: int, week: int) -> dict | None:
        start, _ = _week_range(year, week)
        before = [
            s
            for s in self._data["snapshots"]
            if (d := self._snap_date(s)) and d < start
        ]
        return before[-1] if before else None
