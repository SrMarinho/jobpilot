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

    def job_funnel(self, period: WeekPeriod) -> dict:
        """Funil da candidatura: avaliadas → aprovadas → aplicadas.

        Diferente de ``funnels()``, que conta eventos por feature. Aqui o
        assunto é a vaga: quantas o LLM olhou, quantas passaram e quantas
        viraram candidatura de fato. A distância entre aprovada e aplicada é o
        que revela formulário travando ou quota cortando o run.
        """
        evaluated = self.repo.evaluated()
        in_period = [
            v
            for v in evaluated.values()
            if isinstance(v, dict) and period.contains(v.get("evaluated_at") or "")
        ]
        approved = [v for v in in_period if v.get("matches")]
        applied_count = self.count_entries(self.repo.applied(), "applied_at", period)

        def _pct(part: int, whole: int) -> float:
            return round(part / whole * 100, 1) if whole else 0.0

        by_site: dict[str, dict[str, int]] = {}
        for job in in_period:
            site = job.get("site") or "unknown"
            bucket = by_site.setdefault(site, {"evaluated": 0, "approved": 0})
            bucket["evaluated"] += 1
            if job.get("matches"):
                bucket["approved"] += 1

        return {
            "evaluated": len(in_period),
            "approved": len(approved),
            "applied": applied_count,
            "approval_rate": _pct(len(approved), len(in_period)),
            # Aprovadas que não viraram candidatura ficam na fila (jobs queue).
            "apply_rate": _pct(applied_count, len(approved)),
            "pending": max(0, len(approved) - applied_count),
            "by_site": by_site,
        }

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

    # ── Índice de presença (substituto do SSI) ────────────────────
    #: Semanas anteriores que formam a régua ("sua média").
    PRESENCE_BASELINE_WEEKS = 4

    def presence_inputs(self, period: WeekPeriod, snapshots: dict) -> dict:
        """Métricas brutas da semana que alimentam o índice de presença.

        ``snapshots`` = {"views": [...], "appearances": [...]} já carregados,
        para não reler o histórico a cada semana calculada.
        """
        eng = self.engagement(period)
        engaged_people = {
            p.get("author")
            for p in self.repo.engaged()
            if isinstance(p, dict) and p.get("week") == period.key and p.get("author")
        }
        return {
            "views": _latest_value(snapshots["views"], period, "views"),
            "appearances": _latest_value(snapshots["appearances"], period, "count"),
            "posts": self.autopost(period).get("published", 0),
            "invites": self.connections(period),
            "comments": eng["comments"],
            "shares": eng["shares"],
            "likes": eng["likes"],
            "dms": self.followup(period).get("sent", 0),
            "people": len(engaged_people),
        }

    def presence(self, period: WeekPeriod) -> dict | None:
        """Índice da semana, deltas vs semana anterior e as métricas brutas.

        Mesmo formato que o bloco de SSI tinha (``current`` + ``delta_<pilar>``),
        então quem renderizava o SSI renderiza isto sem outra adaptação.
        """
        from src.core.use_cases.presence_index import baseline, score
        from src.core.use_cases.profile_views_tracker import ProfileViewsTracker
        from src.core.use_cases.search_appearances_tracker import (
            SearchAppearancesTracker,
        )

        snapshots = {
            "views": ProfileViewsTracker().sorted_snapshots(),
            "appearances": SearchAppearancesTracker().sorted_snapshots(),
        }
        n = self.PRESENCE_BASELINE_WEEKS
        weeks = [period]
        for _ in range(n + 1):
            weeks.append(weeks[-1].previous())
        inputs = [self.presence_inputs(w, snapshots) for w in weeks]

        cur_values = inputs[0]
        if not any(cur_values.values()):
            return None
        cur = score(cur_values, baseline(inputs[1 : n + 1]))
        prev = score(inputs[1], baseline(inputs[2 : n + 2]))

        out: dict = {"current": cur, "inputs": cur_values}
        for key in cur:
            out[f"delta_{key}"] = round(cur[key] - prev[key], 1)
        return out


def _latest_value(snaps: list[dict], period: WeekPeriod, field: str) -> int | None:
    """Último valor capturado dentro da semana; ``None`` se não houve captura."""
    start, end = period.range
    value = None
    for s in snaps:
        d = s.get("date") or ""
        if start.isoformat() <= d <= end.isoformat() and s.get(field) is not None:
            value = s[field]
    return value
