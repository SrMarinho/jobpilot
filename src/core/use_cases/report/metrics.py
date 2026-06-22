from datetime import date, datetime

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
        variants: dict[str, int] = {}
        for p in self.repo.engaged():
            if not isinstance(p, dict) or p.get("week") != period.key:
                continue
            acts = p.get("actions") or []
            likes += "like" in acts
            comments += "comment" in acts
            shares += "share" in acts
            a = p.get("author") or "unknown"
            authors[a] = authors.get(a, 0) + 1
            if "comment" in acts and p.get("variant"):
                v = p["variant"]
                variants[v] = variants.get(v, 0) + 1
        return {
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "top_authors": sorted(authors.items(), key=lambda x: -x[1])[:5],
            "by_variant": variants,
        }

    # ── autopost ─────────────────────────────────────────────────
    def autopost(self, period: WeekPeriod) -> dict:
        data = self.repo.autopost()
        posts = [
            p
            for p in data.get("posts", [])
            if isinstance(p, dict) and p.get("week") == period.key
        ]
        drafts = [
            d
            for d in data.get("drafts", [])
            if isinstance(d, dict) and d.get("week") == period.key
        ]
        by_source: dict[str, int] = {}
        by_format: dict[str, int] = {}
        chars: list[int] = []
        for p in posts:
            by_source[p.get("source", "?")] = by_source.get(p.get("source", "?"), 0) + 1
            by_format[p.get("format", "?")] = by_format.get(p.get("format", "?"), 0) + 1
            chars.append(p.get("chars") or len(p.get("content", "")))
        status: dict[str, int] = {}
        for d in drafts:
            status[d.get("status", "?")] = status.get(d.get("status", "?"), 0) + 1
        return {
            "published": len(posts),
            "by_source": by_source,
            "by_format": by_format,
            "generated": len(drafts),
            "approved": status.get("approved", 0),
            "rejected": status.get("rejected", 0),
            "expired": status.get("expired", 0),
            "posted": status.get("posted", 0),
            "avg_chars": int(sum(chars) / len(chars)) if chars else 0,
        }

    # ── follow-up DM ─────────────────────────────────────────────
    def followup(self, period: WeekPeriod) -> dict:
        data = self.repo.followup()
        sent = [
            s
            for s in data.get("sent", [])
            if isinstance(s, dict) and s.get("week") == period.key
        ]
        drafts = [
            d
            for d in data.get("drafts", [])
            if isinstance(d, dict) and d.get("week") == period.key
        ]
        return {
            "sent": len(sent),
            "generated": len(drafts),
        }

    # ── events-based metrics ──────────────────────────────────────

    def _events_in_period(self, period: WeekPeriod) -> list[dict]:
        return [e for e in self.repo.events() if e.get("week") == period.key]

    def failures(self, period: WeekPeriod) -> dict[str, int]:
        """Count failed events per feature in the period."""
        counts: dict[str, int] = {}
        for ev in self._events_in_period(period):
            if not ev.get("ok", True):
                feat = ev.get("feature", "?")
                counts[feat] = counts.get(feat, 0) + 1
        return counts

    def funnels(self, period: WeekPeriod) -> dict[str, dict[str, int]]:
        """Event counts per step per feature (generated→approved→posted, etc.)."""
        evs = self._events_in_period(period)

        def _count(feature: str, event: str) -> int:
            return sum(
                1
                for e in evs
                if e.get("feature") == feature
                and e.get("event") == event
                and e.get("ok", True)
            )

        feature_steps = [
            ("autopost", ["generated", "approved", "posted", "publish_fail"]),
            ("engage", ["offered", "approved", "posted"]),
            ("followup", ["generated", "sent"]),
            ("connect", ["sent"]),
            ("apply", ["submitted"]),
        ]
        result: dict[str, dict[str, int]] = {}
        for feature, steps in feature_steps:
            counts = {step: _count(feature, step) for step in steps}
            if any(counts.values()):
                result[feature] = counts
        return result

    def latency(self, period: WeekPeriod) -> dict[str, dict[str, int]]:
        """Average seconds between paired events, matched by key field."""
        evs = self._events_in_period(period)
        pairs = [
            ("autopost", "generated", "approved"),
            ("autopost", "approved", "posted"),
        ]
        result: dict[str, dict[str, int]] = {}
        for feature, ev_a, ev_b in pairs:
            a_map = {
                e["key"]: e["ts"]
                for e in evs
                if e.get("feature") == feature
                and e.get("event") == ev_a
                and e.get("key")
            }
            b_map = {
                e["key"]: e["ts"]
                for e in evs
                if e.get("feature") == feature
                and e.get("event") == ev_b
                and e.get("key")
            }
            deltas = []
            for k, ts_a in a_map.items():
                if k in b_map:
                    try:
                        d = (
                            datetime.fromisoformat(b_map[k])
                            - datetime.fromisoformat(ts_a)
                        ).total_seconds()
                        if d >= 0:
                            deltas.append(d)
                    except Exception:
                        pass
            if deltas:
                label = f"{ev_a}_to_{ev_b}_avg_s"
                result.setdefault(feature, {})[label] = int(sum(deltas) / len(deltas))
        return result

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
