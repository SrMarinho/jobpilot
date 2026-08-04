from .metrics import MetricsCalculator
from .period import WeekPeriod
from .repository import ReportRepository


class ReportBuilder:
    """Assembles report dicts from repository data + calculated metrics."""

    def __init__(
        self,
        repo: ReportRepository | None = None,
        metrics: MetricsCalculator | None = None,
    ):
        self.repo = repo or ReportRepository()
        self.metrics = metrics or MetricsCalculator(self.repo)

    def weekly(self, period: WeekPeriod) -> dict:
        m = self.metrics
        applied = self.repo.applied()
        rejected = self.repo.rejected()
        prev = self.repo.load_saved_report(period.previous().key)

        applications = m.count_entries(applied, "applied_at", period)
        rejections = m.count_entries(rejected, "rejected_at", period)
        total_seen = applications + rejections

        connections = m.connections(period)
        engagement = m.engagement(period)
        autopost = m.autopost(period)
        failures = m.failures(period)
        funnels = m.funnels(period)
        job_funnel = m.job_funnel(period)
        latency = m.latency(period)
        goals = self._goals_progress(
            applications=applications,
            connections=connections,
            posts=autopost.get("published", 0),
            comments=engagement.get("comments", 0),
        )

        return {
            "week": period.key,
            "range": period.label_range,
            "applications": applications,
            "connections": connections,
            "rejections": rejections,
            "rejection_breakdown": m.rejection_breakdown(rejected, period),
            "level_breakdown": m.level_breakdown(applied, period),
            "site_applications": m.site_breakdown(applied, "applied_at", period),
            "site_rejections": m.site_breakdown(rejected, "rejected_at", period),
            "site_avg_salary": m.site_avg_salary(applied, period),
            "match_rate_pct": round(applications / total_seen * 100)
            if total_seen
            else 0,
            "avg_salary_offered": m.avg_salary(applied, period),
            "qa_pending": m.qa_pending(),
            "top_skills": m.top_skills(3),
            "engagement": engagement,
            "autopost": autopost,
            "followup": m.followup(period),
            "goals": goals,
            "failures": failures,
            "funnels": funnels,
            "job_funnel": job_funnel,
            "latency": latency,
            "ssi": m.ssi(period),
            "prev_applications": prev.get("applications") if prev else None,
            "prev_connections": prev.get("connections") if prev else None,
            "prev_site_applications": (prev.get("site_applications") if prev else None)
            or {},
        }

    @staticmethod
    def _goals_progress(
        applications: int, connections: int, posts: int, comments: int
    ) -> dict:
        from src.core.use_cases.goals_tracker import GoalsTracker

        targets = GoalsTracker().all()
        actual = {
            "applications": applications,
            "connections": connections,
            "posts": posts,
            "comments": comments,
        }
        rows = []
        behind = []
        for key, target in targets.items():
            got = actual.get(key, 0)
            pct = round(got / target * 100) if target else 100
            ok = got >= target
            rows.append(
                {"key": key, "target": target, "actual": got, "pct": pct, "ok": ok}
            )
            if not ok:
                behind.append(key)
        return {"rows": rows, "behind": behind}

    def annual(self, year: int) -> dict:
        m = self.metrics
        applied = self.repo.applied()
        rejected = self.repo.rejected()

        breakdown: dict[str, int] = {}
        level_breakdown: dict[str, int] = {}
        site_apps: dict[str, int] = {}
        site_rejs: dict[str, int] = {}
        applications = rejections = 0
        for w in range(1, 54):
            period = WeekPeriod(year, w)
            applications += m.count_entries(applied, "applied_at", period)
            rejections += m.count_entries(rejected, "rejected_at", period)
            for k, v in m.rejection_breakdown(rejected, period).items():
                breakdown[k] = breakdown.get(k, 0) + v
            for k, v in m.level_breakdown(applied, period).items():
                level_breakdown[k] = level_breakdown.get(k, 0) + v
            for k, v in m.site_breakdown(applied, "applied_at", period).items():
                site_apps[k] = site_apps.get(k, 0) + v
            for k, v in m.site_breakdown(rejected, "rejected_at", period).items():
                site_rejs[k] = site_rejs.get(k, 0) + v

        conn_log = self.repo.connections_log()
        connections = sum(v for k, v in conn_log.items() if k.startswith(str(year)))

        salaries = [
            v["salary_offered"]
            for v in applied.values()
            if isinstance(v, dict)
            and (v.get("applied_at") or "").startswith(str(year))
            and v.get("salary_offered")
        ]
        avg_salary = int(sum(salaries) / len(salaries)) if salaries else None
        total_seen = applications + rejections

        engaged = self.repo.engaged()

        def eng_count(action: str) -> int:
            return sum(
                1
                for p in engaged
                if (p.get("ts") or "").startswith(str(year))
                and action in (p.get("actions") or [])
            )

        return {
            "year": year,
            "week": f"{year}-annual",
            "applications": applications,
            "connections": connections,
            "rejections": rejections,
            "rejection_breakdown": breakdown,
            "level_breakdown": level_breakdown,
            "site_applications": site_apps,
            "site_rejections": site_rejs,
            "match_rate_pct": round(applications / total_seen * 100)
            if total_seen
            else 0,
            "avg_salary_offered": avg_salary,
            "top_skills": m.top_skills(3),
            "engagement": {
                "likes": eng_count("like"),
                "comments": eng_count("comment"),
                "shares": eng_count("share"),
                "top_authors": [],
            },
            "prev_applications": None,
            "prev_connections": None,
        }
