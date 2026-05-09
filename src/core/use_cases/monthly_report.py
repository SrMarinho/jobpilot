import json
from datetime import datetime, date
from pathlib import Path
from src.utils.telegram import send_telegram
from src.config.settings import logger

_FILES_DIR = Path(".local") / "files"
_REPORTS_DIR = _FILES_DIR / "monthly_reports"
_APPLIED_FILE = _FILES_DIR / "applied_jobs.json"
_REJECTED_FILE = _FILES_DIR / "rejected_jobs.json"
_SKILLS_FILE = _FILES_DIR / "skills_gap.json"
_CONNECTIONS_FILE = _FILES_DIR / "connections_log.json"
_QA_FILE = _FILES_DIR / "form_answers.json"


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


def _month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def _count_entries_in_month(data: dict, date_field: str, year: int, month: int) -> int:
    prefix = _month_key(year, month)
    return sum(
        1 for v in data.values()
        if isinstance(v, dict) and (v.get(date_field) or "").startswith(prefix)
    )


def _count_connections_in_month(year: int, month: int) -> int:
    log = _load_json(_CONNECTIONS_FILE)
    prefix = _month_key(year, month)
    return sum(v for k, v in log.items() if k.startswith(prefix))


def _rejection_breakdown(rejected: dict, year: int, month: int) -> dict:
    prefix = _month_key(year, month)
    breakdown: dict[str, int] = {}
    for v in rejected.values():
        if not isinstance(v, dict) or not (v.get("rejected_at") or "").startswith(prefix):
            continue
        reason = v.get("reason", "")
        if "Portuguese" in reason or "language" in reason.lower():
            key = "idioma"
        elif "tech" in reason.lower() or "stack" in reason.lower():
            key = "stack"
        elif "remote" in reason.lower() or "remoto" in reason.lower() or "hybrid" in reason.lower():
            key = "não remoto"
        elif "seniority" in reason.lower() or "level" in reason.lower() or "nível" in reason.lower():
            key = "nível"
        else:
            key = "outros"
        breakdown[key] = breakdown.get(key, 0) + 1
    return breakdown


def _avg_salary(applied: dict, year: int, month: int) -> int | None:
    prefix = _month_key(year, month)
    salaries = [
        v["salary_offered"] for v in applied.values()
        if isinstance(v, dict)
        and (v.get("applied_at") or "").startswith(prefix)
        and v.get("salary_offered")
    ]
    return int(sum(salaries) / len(salaries)) if salaries else None


def _level_breakdown(applied: dict, year: int, month: int) -> dict:
    prefix = _month_key(year, month)
    breakdown: dict[str, int] = {}
    for v in applied.values():
        if not isinstance(v, dict) or not (v.get("applied_at") or "").startswith(prefix):
            continue
        level = v.get("level", "unknown")
        breakdown[level] = breakdown.get(level, 0) + 1
    return breakdown


def _site_breakdown(data: dict, date_field: str, year: int, month: int) -> dict:
    prefix = _month_key(year, month)
    breakdown: dict[str, int] = {}
    for v in data.values():
        if not isinstance(v, dict) or not (v.get(date_field) or "").startswith(prefix):
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


def _site_avg_salary(applied: dict, year: int, month: int) -> dict:
    prefix = _month_key(year, month)
    buckets: dict[str, list[int]] = {}
    for v in applied.values():
        if not isinstance(v, dict) or not (v.get("applied_at") or "").startswith(prefix):
            continue
        salary = v.get("salary_offered")
        if not salary:
            continue
        site = v.get("site") or "unknown"
        buckets.setdefault(site, []).append(salary)
    return {s: int(sum(xs) / len(xs)) for s, xs in buckets.items()}


def _top_skills_global(n: int = 3) -> list[tuple[str, int]]:
    skills = _load_json(_SKILLS_FILE)
    sorted_skills = sorted(skills.items(), key=lambda x: x[1].get("count", 0), reverse=True)
    return [(name, data.get("count", 0)) for name, data in sorted_skills[:n]]


def _top_skills_month(year: int, month: int, n: int = 3) -> list[tuple[str, int]]:
    skills = _load_json(_SKILLS_FILE)
    mk = _month_key(year, month)
    month_skills = [
        (name, data.get("month_counts", {}).get(mk, 0))
        for name, data in skills.items()
        if data.get("month_counts", {}).get(mk, 0) > 0
    ]
    return sorted(month_skills, key=lambda x: -x[1])[:n]


def _load_prev_report(year: int, month: int) -> dict | None:
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    path = _REPORTS_DIR / f"{_month_key(prev_year, prev_month)}.json"
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


def generate_report(year: int, month: int) -> dict:
    applied = _load_json(_APPLIED_FILE)
    rejected = _load_json(_REJECTED_FILE)
    prev = _load_prev_report(year, month)

    applications = _count_entries_in_month(applied, "applied_at", year, month)
    connections = _count_connections_in_month(year, month)
    rejections = _count_entries_in_month(rejected, "rejected_at", year, month)
    breakdown = _rejection_breakdown(rejected, year, month)
    level_breakdown = _level_breakdown(applied, year, month)
    avg_salary = _avg_salary(applied, year, month)
    top_skills = _top_skills_global(3)
    top_skills_month = _top_skills_month(year, month, 3)
    total_seen = applications + rejections
    match_rate = round(applications / total_seen * 100) if total_seen else 0

    site_apps = _site_breakdown(applied, "applied_at", year, month)
    site_rejs = _site_breakdown(rejected, "rejected_at", year, month)
    site_avg_salary = _site_avg_salary(applied, year, month)
    qa_pending = _qa_pending_count()

    return {
        "month": _month_key(year, month),
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
        "top_skills_month": [{"skill": s, "count": c} for s, c in top_skills_month],
        "prev_applications": prev.get("applications") if prev else None,
        "prev_connections": prev.get("connections") if prev else None,
        "prev_site_applications": (prev.get("site_applications") if prev else None) or {},
    }


def generate_year_report(year: int) -> dict:
    applied = _load_json(_APPLIED_FILE)
    rejected = _load_json(_REJECTED_FILE)
    prefix = str(year)

    applications = sum(_count_entries_in_month(applied, "applied_at", year, m) for m in range(1, 13))
    connections = _count_connections_in_month(year, 0)  # handled below
    rejections = sum(_count_entries_in_month(rejected, "rejected_at", year, m) for m in range(1, 13))

    # Connections: sum all months of the year
    conn_log = _load_json(_CONNECTIONS_FILE)
    connections = sum(v for k, v in conn_log.items() if k.startswith(prefix))

    # Merge breakdowns across all months
    breakdown: dict[str, int] = {}
    level_breakdown: dict[str, int] = {}
    site_apps: dict[str, int] = {}
    site_rejs: dict[str, int] = {}
    for m in range(1, 13):
        for k, v in _rejection_breakdown(rejected, year, m).items():
            breakdown[k] = breakdown.get(k, 0) + v
        for k, v in _level_breakdown(applied, year, m).items():
            level_breakdown[k] = level_breakdown.get(k, 0) + v
        for k, v in _site_breakdown(applied, "applied_at", year, m).items():
            site_apps[k] = site_apps.get(k, 0) + v
        for k, v in _site_breakdown(rejected, "rejected_at", year, m).items():
            site_rejs[k] = site_rejs.get(k, 0) + v

    # Avg salary across year
    mk_prefix = str(year)
    salaries = [
        v["salary_offered"] for v in applied.values()
        if isinstance(v, dict)
        and (v.get("applied_at") or "").startswith(mk_prefix)
        and v.get("salary_offered")
    ]
    avg_salary = int(sum(salaries) / len(salaries)) if salaries else None

    total_seen = applications + rejections
    match_rate = round(applications / total_seen * 100) if total_seen else 0

    return {
        "year": year,
        "month": f"{year}-annual",
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
        "top_skills_month": [],
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
        f"\n    {i+1}. {s['skill']} ({s['count']}x)"
        for i, s in enumerate(report.get("top_skills", []))
    )
    salary_line = (
        f"\n💰 Salário médio estimado: R$ {report['avg_salary_offered']:,.0f}".replace(",", ".")
        if report.get("avg_salary_offered") else ""
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

    return (
        f"📊 <b>Relatório Anual — {year}</b>\n\n"
        f"✅ Candidaturas enviadas: <b>{report['applications']}</b>\n"
        f"🤝 Conexões feitas: <b>{report['connections']}</b>\n"
        f"❌ Vagas rejeitadas: <b>{report['rejections']}</b>\n"
        f"🎯 Taxa de match: <b>{report['match_rate_pct']}%</b>"
        f"{salary_line}\n\n"
        f"🌐 <b>Por site:</b>{site_lines or ' —'}\n\n"
        f"🎓 <b>Candidaturas por nível:</b>{level_lines or ' —'}\n\n"
        f"📋 <b>Motivos de rejeição:</b>{breakdown_lines or ' —'}\n\n"
        f"🔥 <b>Top 3 skills mais exigidas:</b>{skills_lines or ' —'}"
    )


def _save_report(report: dict) -> None:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _REPORTS_DIR / f"{report['month']}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Monthly report saved: {path}")


def _format_report(report: dict) -> str:
    month_label = datetime.strptime(report["month"], "%Y-%m").strftime("%B %Y").capitalize()
    breakdown = report.get("rejection_breakdown", {})

    apps = report["applications"]
    conns = report["connections"]
    apps_delta = _delta(apps, report.get("prev_applications"))
    conns_delta = _delta(conns, report.get("prev_connections"))

    breakdown_lines = "".join(
        f"\n    • {k}: {v}x" for k, v in sorted(breakdown.items(), key=lambda x: -x[1])
    )
    skills_month = report.get("top_skills_month", [])
    skills_month_lines = "".join(
        f"\n    {i+1}. {s['skill']} ({s['count']}x)"
        for i, s in enumerate(skills_month)
    )
    skills_global = report.get("top_skills", [])
    skills_global_lines = "".join(
        f"\n    {i+1}. {s['skill']} ({s['count']}x)"
        for i, s in enumerate(skills_global)
    )
    salary_line = (
        f"\n💰 Salário médio estimado: R$ {report['avg_salary_offered']:,.0f}".replace(",", ".")
        if report.get("avg_salary_offered") else ""
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
        site_lines_parts.append(f"\n    • {s}: {a} aplic{delta} / {r} rej ({rate}%{sal_str})")
    site_lines = "".join(site_lines_parts)

    qa_pending = report.get("qa_pending", 0)
    qa_line = f"\n📝 Respostas pendentes: <b>{qa_pending}</b>" if qa_pending else ""

    return (
        f"📊 <b>Relatório Mensal — {month_label}</b>\n\n"
        f"✅ Candidaturas enviadas: <b>{apps}</b>{apps_delta}\n"
        f"🤝 Conexões feitas: <b>{conns}</b>{conns_delta}\n"
        f"❌ Vagas rejeitadas: <b>{report['rejections']}</b>\n"
        f"🎯 Taxa de match: <b>{report['match_rate_pct']}%</b>"
        f"{salary_line}"
        f"{qa_line}\n\n"
        f"🌐 <b>Por site:</b>{site_lines or ' —'}\n\n"
        f"🎓 <b>Candidaturas por nível:</b>{level_lines or ' —'}\n\n"
        f"📋 <b>Motivos de rejeição:</b>{breakdown_lines or ' —'}\n\n"
        f"🚫 <b>Skills que mais bloquearam este mês:</b>{skills_month_lines or ' —'}\n\n"
        f"🔥 <b>Top 3 skills mais exigidas (histórico):</b>{skills_global_lines or ' —'}"
    )


def _prev_month(today: date) -> tuple[int, int]:
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def send_report_now() -> None:
    """Always generates and sends the previous month's report (manual use)."""
    today = date.today()
    year, month = _prev_month(today)
    logger.info(f"Generating monthly report for {_month_key(year, month)}...")
    report = generate_report(year, month)
    _save_report(report)
    send_telegram(_format_report(report))
    logger.info("Monthly report sent via Telegram")


def run_monthly_report_scheduled() -> None:
    """Sends the report only once per month — intended for scheduled/startup use."""
    today = date.today()
    year, month = _prev_month(today)
    report_path = _REPORTS_DIR / f"{_month_key(year, month)}.json"
    if report_path.exists():
        logger.info(f"Monthly report for {_month_key(year, month)} already sent, skipping")
        return
    logger.info(f"Generating monthly report for {_month_key(year, month)}...")
    report = generate_report(year, month)
    _save_report(report)
    send_telegram(_format_report(report))
    logger.info("Monthly report sent via Telegram")
