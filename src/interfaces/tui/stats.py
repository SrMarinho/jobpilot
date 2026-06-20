"""Snapshot de métricas para a dashboard TUI.

Lê os mesmos JSONs do report package (sem browser, sem rede) e devolve um
dict achatado pronto pra render. Read-only.
"""

from datetime import date

from src.core.use_cases.report import ReportRepository, WeekPeriod
from src.core.use_cases.report.metrics import MetricsCalculator


def gather_stats() -> dict:
    repo = ReportRepository()
    metrics = MetricsCalculator(repo)
    period = WeekPeriod.current()

    applied = repo.applied()
    rejected = repo.rejected()
    today = date.today().isoformat()

    apps_week = metrics.count_entries(applied, "applied_at", period)
    rej_week = metrics.count_entries(rejected, "rejected_at", period)
    apps_today = sum(
        1
        for v in applied.values()
        if isinstance(v, dict) and (v.get("applied_at") or "").startswith(today)
    )

    engagement = metrics.engagement(period)
    autopost = metrics.autopost(period)
    ssi = metrics.ssi(period)
    connections = metrics.connections(period)
    qa_pending = metrics.qa_pending()

    from src.core.use_cases.goals_tracker import GoalsTracker

    targets = GoalsTracker().all()
    goals = {
        "applications": (apps_week, targets["applications"]),
        "connections": (connections, targets["connections"]),
        "posts": (autopost.get("published", 0), targets["posts"]),
        "comments": (engagement.get("comments", 0), targets["comments"]),
    }

    return {
        "week": period.key,
        "applied_total": len([v for v in applied.values() if isinstance(v, dict)]),
        "rejected_total": len([v for v in rejected.values() if isinstance(v, dict)]),
        "apps_today": apps_today,
        "apps_week": apps_week,
        "rej_week": rej_week,
        "connections_week": connections,
        "qa_pending": qa_pending,
        "engagement": engagement,
        "autopost": autopost,
        "ssi": ssi.get("current") if ssi else None,
        "goals": goals,
    }
