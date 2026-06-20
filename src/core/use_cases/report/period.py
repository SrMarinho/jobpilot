from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True)
class WeekPeriod:
    """Value object for an ISO-ish week (Monday-Sunday), matching
    ``date.strftime('%W')`` semantics used historically by the report."""

    year: int
    week: int

    @property
    def key(self) -> str:
        return f"{self.year:04d}-W{self.week:02d}"

    @property
    def range(self) -> tuple[date, date]:
        jan1 = date(self.year, 1, 1)
        days_to_monday = (7 - jan1.weekday()) % 7
        first_monday = jan1 + timedelta(days=days_to_monday)
        start = first_monday + timedelta(weeks=self.week - 1)
        return start, start + timedelta(days=6)

    @property
    def label_range(self) -> str:
        start, end = self.range
        return f"{start.isoformat()}..{end.isoformat()}"

    def contains(self, dt_str: str) -> bool:
        d = _parse_date(dt_str)
        if d is None:
            return False
        start, end = self.range
        return start <= d <= end

    def previous(self) -> WeekPeriod:
        """The chronologically preceding week (for saved-report lookup)."""
        if self.week <= 1:
            return WeekPeriod(self.year - 1, 52)
        return WeekPeriod(self.year, self.week - 1)

    @classmethod
    def current(cls, today: date | None = None) -> WeekPeriod:
        today = today or date.today()
        return cls(today.isocalendar().year, int(today.strftime("%W")))

    @classmethod
    def previous_of_today(cls, today: date | None = None) -> WeekPeriod:
        today = today or date.today()
        last = today - timedelta(days=7)
        return cls(last.isocalendar().year, int(last.strftime("%W")))

    @classmethod
    def from_key(cls, key: str) -> WeekPeriod:
        """Parse 'YYYY-Www' (e.g. '2026-W25')."""
        parts = key.upper().replace("W", "").split("-")
        return cls(int(parts[0]), int(parts[1]))


def _parse_date(dt_str: str) -> date | None:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str).date()
    except ValueError:
        try:
            return date.fromisoformat(dt_str[:10])
        except ValueError:
            return None
