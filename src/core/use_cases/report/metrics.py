from datetime import date

from .period import WeekPeriod
from .repository import ReportRepository


class MetricsCalculator:
    """Domain aggregations over the source data for a given week.

    Stateless w.r.t. period: every method receives the ``WeekPeriod`` it
    operates on, so the same instance serves weekly and annual reports.
    """

    def __init__(self, repo: ReportRepository):
        self.repo = repo

    # ── generic counters ─────────────────────────────────────────
    @staticmethod
    def count_entries(data: dict, date_field: str, period: WeekPeriod) -> int:
        return sum(
            1
            for v in data.values()
            if isinstance(v, dict) and period.contains(v.get(date_field) or "")
        )

    def connections(self, period: WeekPeriod) -> int:
        log = self.repo.connections_log()
        start, end = period.range
        total = 0
        for k, v in log.items():
            try:
                d = date.fromisoformat(k)
            except ValueError:
                continue
            if start <= d <= end:
                total += v
        return total

    # ── breakdowns ───────────────────────────────────────────────
    def rejection_breakdown(self, rejected: dict, period: WeekPeriod) -> dict:
        breakdown: dict[str, int] = {}
        for v in rejected.values():
            if not isinstance(v, dict) or not period.contains(
                v.get("rejected_at") or ""
            ):
                continue
            key = self._classify_rejection(v.get("reason", ""))
            breakdown[key] = breakdown.get(key, 0) + 1
        return breakdown

    @staticmethod
    def _classify_rejection(reason: str) -> str:
        low = reason.lower()
        if "Portuguese" in reason or "language" in low:
            return "idioma"
        if "tech" in low or "stack" in low:
            return "stack"
        if "remote" in low or "remoto" in low or "hybrid" in low:
            return "não remoto"
        if "seniority" in low or "level" in low or "nível" in low:
            return "nível"
        return "outros"

    def level_breakdown(self, applied: dict, period: WeekPeriod) -> dict:
        breakdown: dict[str, int] = {}
        for v in applied.values():
            if not isinstance(v, dict) or not period.contains(
                v.get("applied_at") or ""
            ):
                continue
            level = v.get("level", "unknown")
            breakdown[level] = breakdown.get(level, 0) + 1
        return breakdown

    def site_breakdown(self, data: dict, date_field: str, period: WeekPeriod) -> dict:
        breakdown: dict[str, int] = {}
        for v in data.values():
            if not isinstance(v, dict) or not period.contains(v.get(date_field) or ""):
                continue
            site = v.get("site") or "unknown"
            breakdown[site] = breakdown.get(site, 0) + 1
        return breakdown

    # ── salary ───────────────────────────────────────────────────
    def avg_salary(self, applied: dict, period: WeekPeriod) -> int | None:
        salaries = [
            v["salary_offered"]
            for v in applied.values()
            if isinstance(v, dict)
            and period.contains(v.get("applied_at") or "")
            and v.get("salary_offered")
        ]
        return int(sum(salaries) / len(salaries)) if salaries else None

    def site_avg_salary(self, applied: dict, period: WeekPeriod) -> dict:
        buckets: dict[str, list[int]] = {}
        for v in applied.values():
            if not isinstance(v, dict) or not period.contains(
                v.get("applied_at") or ""
            ):
                continue
            salary = v.get("salary_offered")
            if not salary:
                continue
            buckets.setdefault(v.get("site") or "unknown", []).append(salary)
        return {s: int(sum(xs) / len(xs)) for s, xs in buckets.items()}

    # ── misc ─────────────────────────────────────────────────────
    def qa_pending(self) -> int:
        qa = self.repo.qa()
        n = 0
        for entry in qa.values():
            if isinstance(entry, dict):
                if not (entry.get("answer") or "").strip():
                    n += 1
            elif not entry:
                n += 1
        return n

    def top_skills(self, n: int = 3) -> list[dict]:
        skills = self.repo.skills()
        ordered = sorted(
            skills.items(), key=lambda x: x[1].get("count", 0), reverse=True
        )
        return [
            {"skill": name, "count": data.get("count", 0)} for name, data in ordered[:n]
        ]

    # ── engagement ───────────────────────────────────────────────
    def engagement(self, period: WeekPeriod) -> dict:
        likes = comments = shares = 0
        authors: dict[str, int] = {}
        for p in self.repo.engaged():
            if not isinstance(p, dict) or p.get("week") != period.key:
                continue
            acts = p.get("actions") or []
            likes += "like" in acts
            comments += "comment" in acts
            shares += "share" in acts
            a = p.get("author") or "unknown"
            authors[a] = authors.get(a, 0) + 1
        return {
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "top_authors": sorted(authors.items(), key=lambda x: -x[1])[:5],
        }

    # ── SSI ──────────────────────────────────────────────────────
    def ssi(self, period: WeekPeriod) -> dict | None:
        from src.core.use_cases.ssi_tracker import SSITracker

        tracker = SSITracker()
        cur = tracker.latest_in_week(period.year, period.week)
        if not cur:
            return None
        prev = tracker.latest_before_week(period.year, period.week)

        def delta(key: str) -> float | None:
            if not prev or key not in prev or key not in cur:
                return None
            return round(cur[key] - prev[key], 1)

        return {
            "current": cur,
            "delta_total": delta("total"),
            "delta_brand": delta("brand"),
            "delta_find_people": delta("find_people"),
            "delta_engage_insights": delta("engage_insights"),
            "delta_relationships": delta("relationships"),
        }
