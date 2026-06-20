_LEVEL_ORDER = ["junior", "pleno", "senior", "unknown"]
_SITE_ORDER = ["linkedin", "indeed", "glassdoor", "unknown"]


def _delta(current: int, previous: int | None) -> str:
    if previous is None:
        return ""
    diff = current - previous
    if diff > 0:
        return f" (↑{diff})"
    if diff < 0:
        return f" (↓{abs(diff)})"
    return " (=)"


def _money(value: float) -> str:
    return f"R$ {value:,.0f}".replace(",", ".")


class ReportFormatter:
    """Renders report dicts to Telegram-flavored HTML strings.

    Pure presentation — no data access, no calculations.
    """

    # ── weekly ───────────────────────────────────────────────────
    def weekly(self, report: dict) -> str:
        apps = report["applications"]
        conns = report["connections"]

        salary_line = (
            f"\n💰 Salário médio estimado: {_money(report['avg_salary_offered'])}"
            if report.get("avg_salary_offered")
            else ""
        )
        qa_pending = report.get("qa_pending", 0)
        qa_line = f"\n📝 Respostas pendentes: <b>{qa_pending}</b>" if qa_pending else ""

        return (
            f"📊 <b>Relatório Semanal — {report.get('week', '')}</b>\n"
            f"<i>{report.get('range', '')}</i>\n\n"
            f"✅ Candidaturas enviadas: <b>{apps}</b>"
            f"{_delta(apps, report.get('prev_applications'))}\n"
            f"🤝 Conexões feitas: <b>{conns}</b>"
            f"{_delta(conns, report.get('prev_connections'))}\n"
            f"❌ Vagas rejeitadas: <b>{report['rejections']}</b>\n"
            f"🎯 Taxa de match: <b>{report['match_rate_pct']}%</b>"
            f"{salary_line}"
            f"{qa_line}"
            f"{self._ssi_block(report.get('ssi'))}"
            f"{self._engagement_block(report.get('engagement'))}"
            f"{self._autopost_block(report.get('autopost'))}"
            f"{self._followup_block(report.get('followup'))}"
            f"{self._goals_block(report.get('goals'))}\n\n"
            f"🌐 <b>Por site:</b>"
            f"{self._site_block(report, with_delta=True) or ' —'}\n\n"
            f"🎓 <b>Candidaturas por nível:</b>"
            f"{self._level_lines(report) or ' —'}\n\n"
            f"📋 <b>Motivos de rejeição:</b>"
            f"{self._breakdown_lines(report) or ' —'}\n\n"
            f"🔥 <b>Top 3 skills mais exigidas:</b>"
            f"{self._skills_lines(report) or ' —'}"
        )

    # ── annual ───────────────────────────────────────────────────
    def annual(self, report: dict) -> str:
        salary_line = (
            f"\n💰 Salário médio estimado: {_money(report['avg_salary_offered'])}"
            if report.get("avg_salary_offered")
            else ""
        )
        eng = report.get("engagement", {})
        eng_line = (
            f"\n🤝 <b>Engagement:</b> ❤️ {eng.get('likes', 0)} | "
            f"💬 {eng.get('comments', 0)} | 🔁 {eng.get('shares', 0)}"
        )
        return (
            f"📊 <b>Relatório Anual — {report.get('year', '')}</b>\n\n"
            f"✅ Candidaturas enviadas: <b>{report['applications']}</b>\n"
            f"🤝 Conexões feitas: <b>{report['connections']}</b>\n"
            f"❌ Vagas rejeitadas: <b>{report['rejections']}</b>\n"
            f"🎯 Taxa de match: <b>{report['match_rate_pct']}%</b>"
            f"{salary_line}"
            f"{eng_line}\n\n"
            f"🌐 <b>Por site:</b>"
            f"{self._site_block(report, with_delta=False) or ' —'}\n\n"
            f"🎓 <b>Candidaturas por nível:</b>"
            f"{self._level_lines(report) or ' —'}\n\n"
            f"📋 <b>Motivos de rejeição:</b>"
            f"{self._breakdown_lines(report) or ' —'}\n\n"
            f"🔥 <b>Top 3 skills mais exigidas:</b>"
            f"{self._skills_lines(report) or ' —'}"
        )

    # ── shared sections ──────────────────────────────────────────
    @staticmethod
    def _breakdown_lines(report: dict) -> str:
        breakdown = report.get("rejection_breakdown", {})
        return "".join(
            f"\n    • {k}: {v}x"
            for k, v in sorted(breakdown.items(), key=lambda x: -x[1])
        )

    @staticmethod
    def _level_lines(report: dict) -> str:
        levels = report.get("level_breakdown", {})
        return "".join(
            f"\n    • {k}: {v}x" for k in _LEVEL_ORDER if (v := levels.get(k, 0)) > 0
        )

    @staticmethod
    def _skills_lines(report: dict) -> str:
        return "".join(
            f"\n    {i + 1}. {s['skill']} ({s['count']}x)"
            for i, s in enumerate(report.get("top_skills", []))
        )

    @staticmethod
    def _site_block(report: dict, with_delta: bool) -> str:
        site_apps = report.get("site_applications", {})
        site_rejs = report.get("site_rejections", {})
        site_avg = report.get("site_avg_salary", {})
        prev_site_apps = report.get("prev_site_applications", {}) or {}
        parts = []
        for s in _SITE_ORDER:
            a = site_apps.get(s, 0)
            r = site_rejs.get(s, 0)
            if a == 0 and r == 0:
                continue
            seen = a + r
            rate = round(a / seen * 100) if seen else 0
            if with_delta:
                delta = _delta(a, prev_site_apps.get(s) if prev_site_apps else None)
                sal = site_avg.get(s)
                sal_str = f", {_money(sal)}" if sal else ""
                parts.append(
                    f"\n    • {s}: {a} aplic{delta} / {r} rej ({rate}%{sal_str})"
                )
            else:
                parts.append(f"\n    • {s}: {a} aplic / {r} rej ({rate}%)")
        return "".join(parts)

    @staticmethod
    def _engagement_block(eng: dict | None) -> str:
        eng = eng or {}
        top_authors = eng.get("top_authors") or []
        top_lines = "".join(f"\n    • {name} ({n}x)" for name, n in top_authors)
        by_variant = eng.get("by_variant") or {}
        variant_lines = "".join(
            f"\n    • {k}: {v}x"
            for k, v in sorted(by_variant.items(), key=lambda x: -x[1])
        )
        return (
            f"\n\n🤝 <b>Engagement (semana):</b>\n"
            f"    ❤️ Likes: <b>{eng.get('likes', 0)}</b>\n"
            f"    💬 Comments: <b>{eng.get('comments', 0)}</b>\n"
            f"    🔁 Shares: <b>{eng.get('shares', 0)}</b>"
            + (f"\n    👥 Top autores:{top_lines}" if top_authors else "")
            + (f"\n    🧪 A/B comentário:{variant_lines}" if by_variant else "")
        )

    @staticmethod
    def _autopost_block(ap: dict | None) -> str:
        ap = ap or {}
        published = ap.get("published", 0)
        generated = ap.get("generated", 0)
        if not published and not generated:
            return ""
        approval = round(ap.get("approved", 0) / generated * 100) if generated else 0
        fmt_parts = "".join(
            f"\n    • {k}: {v}x"
            for k, v in sorted(ap.get("by_format", {}).items(), key=lambda x: -x[1])
        )
        return (
            f"\n\n📝 <b>Autopost (semana):</b>\n"
            f"    🚀 Publicados: <b>{published}</b>\n"
            f"    🧪 Gerados: {generated} · ✅ {ap.get('approved', 0)} · "
            f"❌ {ap.get('rejected', 0)} · ⏰ {ap.get('expired', 0)} "
            f"(aprovação {approval}%)\n"
            f"    ✍️ Média: {ap.get('avg_chars', 0)} chars"
            + (f"\n    📑 Por formato:{fmt_parts}" if fmt_parts else "")
        )

    @staticmethod
    def _followup_block(fu: dict | None) -> str:
        fu = fu or {}
        sent = fu.get("sent", 0)
        generated = fu.get("generated", 0)
        if not sent and not generated:
            return ""
        return (
            f"\n\n💬 <b>Follow-up DM (semana):</b>\n"
            f"    📤 Enviados: <b>{sent}</b> · 🧪 Gerados: {generated}"
        )

    @staticmethod
    def _goals_block(goals: dict | None) -> str:
        goals = goals or {}
        rows = goals.get("rows") or []
        if not rows:
            return ""
        labels = {
            "applications": "Candidaturas",
            "connections": "Conexões",
            "posts": "Posts",
            "comments": "Comentários",
        }
        lines = []
        for r in rows:
            mark = "✅" if r["ok"] else "🔸"
            label = labels.get(r["key"], r["key"])
            lines.append(
                f"\n    {mark} {label}: {r['actual']}/{r['target']} ({r['pct']}%)"
            )
        behind = goals.get("behind") or []
        alert = (
            f"\n    ⚠️ Atrás em: {', '.join(labels.get(k, k) for k in behind)}"
            if behind
            else "\n    🎉 Todas as metas batidas!"
        )
        return f"\n\n🎯 <b>Metas (semana):</b>{''.join(lines)}{alert}"

    @staticmethod
    def _ssi_block(ssi: dict | None) -> str:
        if not ssi or not ssi.get("current"):
            return "\n\n📈 <b>SSI:</b> — (sem captura esta semana)"
        cur = ssi["current"]

        def dstr(key: str) -> str:
            d = ssi.get(f"delta_{key}")
            if d is None:
                return ""
            if d > 0:
                return f" (↑{d})"
            if d < 0:
                return f" (↓{abs(d)})"
            return " (=)"

        rank_parts = []
        if cur.get("rank_industry_pct") is not None:
            rank_parts.append(f"Top {cur['rank_industry_pct']}% no setor")
        if cur.get("rank_network_pct") is not None:
            rank_parts.append(f"Top {cur['rank_network_pct']}% na rede")
        rank_line = f"\n    📊 {' · '.join(rank_parts)}" if rank_parts else ""

        return (
            f"\n\n📈 <b>SSI (Social Selling Index): "
            f"{cur['total']}/100{dstr('total')}</b>\n"
            f"    🏷️ Marca profissional:   {cur['brand']}/25{dstr('brand')}\n"
            f"    🔍 Pessoas certas:        {cur['find_people']}/25"
            f"{dstr('find_people')}\n"
            f"    💡 Interagir c/ insights: {cur['engage_insights']}/25"
            f"{dstr('engage_insights')}\n"
            f"    🤝 Relacionamentos:       {cur['relationships']}/25"
            f"{dstr('relationships')}"
            f"{rank_line}"
        )

    # ── plaintext (CLI stdout) ───────────────────────────────────
    @staticmethod
    def to_plaintext(html: str) -> str:
        return (
            html.replace("<b>", "")
            .replace("</b>", "")
            .replace("<i>", "")
            .replace("</i>", "")
        )
