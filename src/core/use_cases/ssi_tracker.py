from datetime import date, timedelta
from pathlib import Path

from src.config.settings import files_dir
from src.core.persistence.daily_snapshot_tracker import DailySnapshotTracker

SSI_HISTORY_FILE = files_dir / "ssi_history.json"


def _week_range(year: int, week: int) -> tuple[date, date]:
    """Monday-Sunday range matching date.strftime('%W'). Mirrors report.period."""
    jan1 = date(year, 1, 1)
    days_to_monday = (7 - jan1.weekday()) % 7
    first_monday = jan1 + timedelta(days=days_to_monday)
    start = first_monday + timedelta(weeks=week - 1)
    end = start + timedelta(days=6)
    return start, end


class SSITracker(DailySnapshotTracker):
    """Histórico do Social Selling Index (1 snapshot/dia)."""

    table = "ssi_history"

    def __init__(self, path: Path = SSI_HISTORY_FILE):
        super().__init__(path)

    def build_snapshot(self, snapshot: dict) -> dict:
        return dict(snapshot)

    def latest_in_week(self, year: int, week: int) -> dict | None:
        start, end = _week_range(year, week)
        in_week = [
            s
            for s in self.snapshots
            if (d := self.snapshot_date(s)) and start <= d <= end
        ]
        return in_week[-1] if in_week else None

    def latest_before_week(self, year: int, week: int) -> dict | None:
        start, _ = _week_range(year, week)
        before = [
            s for s in self.snapshots if (d := self.snapshot_date(s)) and d < start
        ]
        return before[-1] if before else None
