import json
from datetime import datetime, date, timedelta
from pathlib import Path
from src.utils.telegram import send_telegram
from src.config.settings import logger

_FILES_DIR = Path(".local") / "files"
_REPORTS_DIR = _FILES_DIR / "weekly_reports"
_APPLIED_FILE = _FILES_DIR / "applied_jobs.json"
_REJECTED_FILE = _FILES_DIR / "rejected_jobs.json"
_SKILLS_FILE = _FILES_DIR / "skills_gap.json"
_CONNECTIONS_FILE = _FILES_DIR / "connections_log.json"
_QA_FILE = _FILES_DIR / "form_answers.json"
_ENGAGED_FILE = _FILES_DIR / "engaged_posts.json"


def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_connections(count: int) -> None:
    log = _load_json(_CONNECTIONS_FILE)
    today = date.today().isoformat()
    existing = log.get(today, 0)
    log[today] = existing + count
    _FILES_DIR.mkdir(exist_ok=True)
    _CONNECTIONS_FILE.write_text(json.dumps(log, indent=2), encoding="utf-8")


def _week_key(year: int, week: int) -> str:
    return f"{year:04d}-W{week:02d}"


def _week_range(year: int, week: int) -> tuple[date, date]:
    """ISO-ish: Monday-Sunday. Matches Python date.strftime('%W')."""
    jan1 = date(year, 1, 1)
    days_to_monday = (7 - jan1.weekday()) % 7
    first_monday = jan1 + timedelta(days=days_to_monday)
    start = first_monday + timedelta(weeks=week - 1)
    end = start + timedelta(days=6)
    return start, end


def _is_in_week(dt_str: str, year: int, week: int) -> bool:
    if not dt_str:
        return False
    try:
        d = datetime.fromisoformat(dt_str).date()
    except Exception:
        try:
            d = date.fromisoformat(dt_str[:10])
        except Exception:
            return False
    start, end = _week_range(year, week)
    return start <= d <= end


def _count_entries_in_week(data: dict, date_field: str, year: int, week: int) -> int:
    return sum(
        1
        for v in data.values()
        if isinstance(v, dict) and _is_in_week(v.get(date_field) or "", year, week)
    )


def _count_connections_in_week(year: int, week: int) -> int:
    log = _load_json(_CONNECTIONS_FILE)
    start, end = _week_range(year, week)
    total = 0
    for k, v in log.items():
        try:
            d = date.fromisoformat(k)
        except Exception:
            continue
        if start <= d <= end:
            total += v
    return total


def _engagement_in_week(year: int, week: int) -> dict:
    data = _load_json(_ENGAGED_FILE)
    posts = data.get("engaged", []) if isinstance(data, dict) else []
    likes = comments = shares = 0
    authors: dict[str, int] = {}
    week_key = _week_key(year, week)
    for p in posts:
        if not isinstance(p, dict):
            continue
        if p.get("week") != week_key:
            continue
        acts = p.get("actions") or []
        if "like" in acts:
            likes += 1
        if "comment" in acts:
            comments += 1
        if "share" in acts:
            shares += 1
        a = p.get("author") or "unknown"
        authors[a] = authors.get(a, 0) + 1
    top = sorted(authors.items(), key=lambda x: -x[1])[:5]
    return {
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "top_authors": top,
    }


def _rejection_breakdown(rejected: dict, year: int, week: int) -> dict:
    breakdown: dict[str, int] = {}
    for v in rejected.values():
        if not isinstance(v, dict) or not _is_in_week(
            v.get("rejected_at") or "", year, week
        ):
            continue
        reason = v.get("reason", "")
        if "Portuguese" in reason or "language" in reason.lower():
            key = "idioma"
        elif "tech" in reason.lower() or "stack" in reason.lower():
            key = "stack"
        elif (
            "remote" in reason.lower()
            or "remoto" in reason.lower()
            or "hybrid" in reason.lower()
        ):
            key = "não remoto"
        elif (
            "seniority" in reason.lower()
            or "level" in reason.lower()
            or "nível" in reason.lower()
        ):
            key = "nível"
        else:
            key = "outros"
        breakdown[key] = breakdown.get(key, 0) + 1
    return breakdown


def _avg_salary(applied: dict, year: int, week: int) -> int | None:
    salaries = [
        v["salary_offered"]
        for v in applied.values()
        if isinstance(v, dict)
        and _is_in_week(v.get("applied_at") or "", year, week)
        and v.get("salary_offered")
    ]
    return int(sum(salaries) / len(salaries)) if salaries else None


def _level_breakdown(applied: dict, year: int, week: int) -> dict:
    breakdown: dict[str, int] = {}
    for v in applied.values():
        if not isinstance(v, dict) or not _is_in_week(
            v.get("applied_at") or "", year, week
        ):
            continue
        level = v.get("level", "unknown")
        breakdown[level] = breakdown.get(level, 0) + 1
    return breakdown


def _site_breakdown(data: dict, date_field: str, year: int, week: int) -> dict:
    breakdown: dict[str, int] = {}
    for v in data.values():
        if not isinstance(v, dict) or not _is_in_week(
            v.get(date_field) or "", year, week
        ):
            continue
        site = v.get("site") or "unknown"
        breakdown[site] = breakdown.get(site, 0) + 1
    return breakdown


def _qa_pending_count() -> int:
    qa = _load_json(_QA_FILE)
    n = 0
    for entry in qa.values():
        if isinstance(entry, dict):
            ans = (entry.get("answer") or "").strip()
            if not ans:
                n += 1
        elif not entry:
            n += 1
    return n


def _site_avg_salary(applied: dict, year: int, week: int) -> dict:
    buckets: dict[str, list[int]] = {}
    for v in applied.values():
        if not isinstance(v, dict) or not _is_in_week(
            v.get("applied_at") or "", year, week
        ):
            continue
        salary = v.get("salary_offered")
        if not salary:
            continue
        site = v.get("site") or "unknown"
        buckets.setdefault(site, []).append(salary)
    return {s: int(sum(xs) / len(xs)) for s, xs in buckets.items()}


def _top_skills_global(n: int = 3) -> list[tuple[str, int]]:
    skills = _load_json(_SKILLS_FILE)
    sorted_skills = sorted(
        skills.items(), key=lambda x: x[1].get("count", 0), reverse=True
    )
    return [(name, data.get("count", 0)) for name, data in sorted_skills[:n]]


def _prev_week(today: date) -> tuple[int, int]:
    last_week_day = today - timedelta(days=7)
    return last_week_day.isocalendar().year, int(last_week_day.strftime("%W"))


def _current_week(today: date) -> tuple[int, int]:
    return today.isocalendar().year, int(today.strftime("%W"))


def _load_prev_report(year: int, week: int) -> dict | None:
    if week <= 1:
        prev_year, prev_week = year - 1, 52
    else:
        prev_year, prev_week = year, week - 1
    path = _REPORTS_DIR / f"{_week_key(prev_year, prev_week)}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _delta(current: int, previous: int | None) -> str:
    if previous is None:
        return ""
    diff = current - previous
    if diff > 0:
        return f" (↑{diff})"
    if diff < 0:
        return f" (↓{abs(diff)})"
    return " (=)"


def generate_report(year: int, week: int) -> dict:
    applied = _load_json(_APPLIED_FILE)
    rejected = _load_json(_REJECTED_FILE)
    prev = _load_prev_report(year, week)

    applications = _count_entries_in_week(applied, "applied_at", year, week)
    connections = _count_connections_in_week(year, week)
    rejections = _count_entries_in_week(rejected, "rejected_at", year, week)
    breakdown = _rejection_breakdown(rejected, year, week)
    level_breakdown = _level_breakdown(applied, year, week)
    avg_salary = _avg_salary(applied, year, week)
    top_skills = _top_skills_global(3)
    total_seen = applications + rejections
    match_rate = round(applications / total_seen * 100) if total_seen else 0

    site_apps = _site_breakdown(applied, "applied_at", year, week)
    site_rejs = _site_breakdown(rejected, "rejected_at", year, week)
    site_avg_salary = _site_avg_salary(applied, year, week)
    qa_pending = _qa_pending_count()
    engagement = _engagement_in_week(year, week)
    start, end = _week_range(year, week)

    return {
        "week": _week_key(year, week),
        "range": f"{start.isoformat()}..{end.isoformat()}",
        "applications": applications,
        "connections": connections,
        "rejections": rejections,
        "rejection_breakdown": breakdown,
        "level_breakdown": level_breakdown,
        "site_applications": site_apps,
        "site_rejections": site_rejs,
        "site_avg_salary": site_avg_salary,
        "match_rate_pct": match_rate,
        "avg_salary_offered": avg_salary,
        "qa_pending": qa_pending,
        "top_skills": [{"skill": s, "count": c} for s, c in top_skills],
        "engagement": engagement,
        "prev_applications": prev.get("applications") if prev else None,
        "prev_connections": prev.get("connections") if prev else None,
        "prev_site_applications": (prev.get("site_applications") if prev else None)
        or {},
    }


def generate_year_report(year: int) -> dict:
    applied = _load_json(_APPLIED_FILE)
    rejected = _load_json(_REJECTED_FILE)

    breakdown: dict[str, int] = {}
    level_breakdown: dict[str, int] = {}
    site_apps: dict[str, int] = {}
    site_rejs: dict[str, int] = {}
    applications = 0
    rejections = 0
    for w in range(1, 54):
        applications += _count_entries_in_week(applied, "applied_at", year, w)
        rejections += _count_entries_in_week(rejected, "rejected_at", year, w)
        for k, v in _rejection_breakdown(rejected, year, w).items():
            breakdown[k] = breakdown.get(k, 0) + v
        for k, v in _level_breakdown(applied, year, w).items():
            level_breakdown[k] = level_breakdown.get(k, 0) + v
        for k, v in _site_breakdown(applied, "applied_at", year, w).items():
            site_apps[k] = site_apps.get(k, 0) + v
        for k, v in _site_breakdown(rejected, "rejected_at", year, w).items():
            site_rejs[k] = site_rejs.get(k, 0) + v

    conn_log = _load_json(_CONNECTIONS_FILE)
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
    match_rate = round(applications / total_seen * 100) if total_seen else 0

    engaged = _load_json(_ENGAGED_FILE).get("engaged", [])
    eng_likes = sum(
        1
        for p in engaged
        if (p.get("ts") or "").startswith(str(year))
        and "like" in (p.get("actions") or [])
    )
    eng_comments = sum(
        1
        for p in engaged
        if (p.get("ts") or "").startswith(str(year))
        and "comment" in (p.get("actions") or [])
    )
    eng_shares = sum(
        1
        for p in engaged
        if (p.get("ts") or "").startswith(str(year))
        and "share" in (p.get("actions") or [])
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
        "match_rate_pct": match_rate,
        "avg_salary_offered": avg_salary,
        "top_skills": [{"skill": s, "count": c} for s, c in _top_skills_global(3)],
        "engagement": {
            "likes": eng_likes,
            "comments": eng_comments,
            "shares": eng_shares,
            "top_authors": [],
        },
        "prev_applications": None,
        "prev_connections": None,
    }


def _format_year_report(report: dict) -> str:
    year = report.get("year", "")
    breakdown = report.get("rejection_breakdown", {})
    breakdown_lines = "".join(
        f"\n    • {k}: {v}x" for k, v in sorted(breakdown.items(), key=lambda x: -x[1])
    )
    level_breakdown = report.get("level_breakdown", {})
    _level_order = ["junior", "pleno", "senior", "unknown"]
    level_lines = "".join(
        f"\n    • {k}: {v}x"
        for k in _level_order
        if (v := level_breakdown.get(k, 0)) > 0
    )
    skills_lines = "".join(
        f"\n    {i + 1}. {s['skill']} ({s['count']}x)"
        for i, s in enumerate(report.get("top_skills", []))
    )
    salary_line = (
        f"\n💰 Salário médio estimado: R$ {report['avg_salary_offered']:,.0f}".replace(
            ",", "."
        )
        if report.get("avg_salary_offered")
        else ""
    )
    site_apps = report.get("site_applications", {})
    site_rejs = report.get("site_rejections", {})
    _site_order = ["linkedin", "indeed", "glassdoor", "unknown"]
    site_lines_parts = []
    for s in _site_order:
        a = site_apps.get(s, 0)
        r = site_rejs.get(s, 0)
        if a == 0 and r == 0:
            continue
        seen = a + r
        rate = round(a / seen * 100) if seen else 0
        site_lines_parts.append(f"\n    • {s}: {a} aplic / {r} rej ({rate}%)")
    site_lines = "".join(site_lines_parts)

    eng = report.get("engagement", {})
    eng_line = (
        f"\n🤝 <b>Engagement:</b> ❤️ {eng.get('likes', 0)} | "
        f"💬 {eng.get('comments', 0)} | 🔁 {eng.get('shares', 0)}"
    )

    return (
        f"📊 <b>Relatório Anual — {year}</b>\n\n"
        f"✅ Candidaturas enviadas: <b>{report['applications']}</b>\n"
        f"🤝 Conexões feitas: <b>{report['connections']}</b>\n"
        f"❌ Vagas rejeitadas: <b>{report['rejections']}</b>\n"
        f"🎯 Taxa de match: <b>{report['match_rate_pct']}%</b>"
        f"{salary_line}"
        f"{eng_line}\n\n"
        f"🌐 <b>Por site:</b>{site_lines or ' —'}\n\n"
        f"🎓 <b>Candidaturas por nível:</b>{level_lines or ' —'}\n\n"
        f"📋 <b>Motivos de rejeição:</b>{breakdown_lines or ' —'}\n\n"
        f"🔥 <b>Top 3 skills mais exigidas:</b>{skills_lines or ' —'}"
    )


def _save_report(report: dict) -> None:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _REPORTS_DIR / f"{report['week']}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Weekly report saved: {path}")


def _format_report(report: dict) -> str:
    week_label = report.get("week", "")
    rng = report.get("range", "")
    breakdown = report.get("rejection_breakdown", {})

    apps = report["applications"]
    conns = report["connections"]
    apps_delta = _delta(apps, report.get("prev_applications"))
    conns_delta = _delta(conns, report.get("prev_connections"))

    breakdown_lines = "".join(
        f"\n    • {k}: {v}x" for k, v in sorted(breakdown.items(), key=lambda x: -x[1])
    )
    skills_global = report.get("top_skills", [])
    skills_global_lines = "".join(
        f"\n    {i + 1}. {s['skill']} ({s['count']}x)"
        for i, s in enumerate(skills_global)
    )
    salary_line = (
        f"\n💰 Salário médio estimado: R$ {report['avg_salary_offered']:,.0f}".replace(
            ",", "."
        )
        if report.get("avg_salary_offered")
        else ""
    )

    level_breakdown = report.get("level_breakdown", {})
    _level_order = ["junior", "pleno", "senior", "unknown"]
    level_lines = "".join(
        f"\n    • {k}: {v}x"
        for k in _level_order
        if (v := level_breakdown.get(k, 0)) > 0
    )

    site_apps = report.get("site_applications", {})
    site_rejs = report.get("site_rejections", {})
    site_avg = report.get("site_avg_salary", {})
    prev_site_apps = report.get("prev_site_applications", {}) or {}
    _site_order = ["linkedin", "indeed", "glassdoor", "unknown"]
    site_lines_parts = []
    for s in _site_order:
        a = site_apps.get(s, 0)
        r = site_rejs.get(s, 0)
        if a == 0 and r == 0:
            continue
        seen = a + r
        rate = round(a / seen * 100) if seen else 0
        delta = _delta(a, prev_site_apps.get(s) if prev_site_apps else None)
        sal = site_avg.get(s)
        sal_str = f", R$ {f'{sal:,.0f}'.replace(',', '.')}" if sal else ""
        site_lines_parts.append(
            f"\n    • {s}: {a} aplic{delta} / {r} rej ({rate}%{sal_str})"
        )
    site_lines = "".join(site_lines_parts)

    qa_pending = report.get("qa_pending", 0)
    qa_line = f"\n📝 Respostas pendentes: <b>{qa_pending}</b>" if qa_pending else ""

    eng = report.get("engagement", {}) or {}
    top_authors = eng.get("top_authors") or []
    top_authors_lines = "".join(f"\n    • {name} ({n}x)" for name, n in top_authors)
    eng_block = (
        f"\n\n🤝 <b>Engagement (semana):</b>\n"
        f"    ❤️ Likes: <b>{eng.get('likes', 0)}</b>\n"
        f"    💬 Comments: <b>{eng.get('comments', 0)}</b>\n"
        f"    🔁 Shares: <b>{eng.get('shares', 0)}</b>"
        + (f"\n    👥 Top autores:{top_authors_lines}" if top_authors else "")
    )

    return (
        f"📊 <b>Relatório Semanal — {week_label}</b>\n"
        f"<i>{rng}</i>\n\n"
        f"✅ Candidaturas enviadas: <b>{apps}</b>{apps_delta}\n"
        f"🤝 Conexões feitas: <b>{conns}</b>{conns_delta}\n"
        f"❌ Vagas rejeitadas: <b>{report['rejections']}</b>\n"
        f"🎯 Taxa de match: <b>{report['match_rate_pct']}%</b>"
        f"{salary_line}"
        f"{qa_line}"
        f"{eng_block}\n\n"
        f"🌐 <b>Por site:</b>{site_lines or ' —'}\n\n"
        f"🎓 <b>Candidaturas por nível:</b>{level_lines or ' —'}\n\n"
        f"📋 <b>Motivos de rejeição:</b>{breakdown_lines or ' —'}\n\n"
        f"🔥 <b>Top 3 skills mais exigidas:</b>{skills_global_lines or ' —'}"
    )


def send_report_now() -> None:
    """Generates and sends the previous week's report (manual use)."""
    today = date.today()
    year, week = _prev_week(today)
    logger.info(f"Generating weekly report for {_week_key(year, week)}...")
    report = generate_report(year, week)
    _save_report(report)
    send_telegram(_format_report(report))
    logger.info("Weekly report sent via Telegram")


def run_weekly_report_scheduled() -> None:
    """Sends the report only once per week — intended for scheduled/startup use."""
    today = date.today()
    year, week = _prev_week(today)
    report_path = _REPORTS_DIR / f"{_week_key(year, week)}.json"
    if report_path.exists():
        logger.info(f"Weekly report for {_week_key(year, week)} already sent, skipping")
        return
    logger.info(f"Generating weekly report for {_week_key(year, week)}...")
    report = generate_report(year, week)
    _save_report(report)
    send_telegram(_format_report(report))
    logger.info("Weekly report sent via Telegram")
