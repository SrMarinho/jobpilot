import json
from datetime import datetime, date
from pathlib import Path
from src.utils.telegram import send_telegram
from src.config.settings import logger

_FILES_DIR = Path("files")
_REPORTS_DIR = _FILES_DIR / "monthly_reports"
_APPLIED_FILE = _FILES_DIR / "applied_jobs.json"
_REJECTED_FILE = _FILES_DIR / "rejected_jobs.json"
_SKILLS_FILE = _FILES_DIR / "skills_gap.json"
_CONNECTIONS_FILE = _FILES_DIR / "connections_log.json"


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


def _top_skills(n: int = 3) -> list[tuple[str, int]]:
    skills = _load_json(_SKILLS_FILE)
    sorted_skills = sorted(skills.items(), key=lambda x: x[1].get("count", 0), reverse=True)
    return [(name, data.get("count", 0)) for name, data in sorted_skills[:n]]


def generate_report(year: int, month: int) -> dict:
    applied = _load_json(_APPLIED_FILE)
    rejected = _load_json(_REJECTED_FILE)

    applications = _count_entries_in_month(applied, "applied_at", year, month)
    connections = _count_connections_in_month(year, month)
    rejections = _count_entries_in_month(rejected, "rejected_at", year, month)
    breakdown = _rejection_breakdown(rejected, year, month)
    avg_salary = _avg_salary(applied, year, month)
    top_skills = _top_skills(3)
    total_seen = applications + rejections
    match_rate = round(applications / total_seen * 100) if total_seen else 0

    return {
        "month": _month_key(year, month),
        "applications": applications,
        "connections": connections,
        "rejections": rejections,
        "rejection_breakdown": breakdown,
        "match_rate_pct": match_rate,
        "avg_salary_offered": avg_salary,
        "top_skills": [{"skill": s, "count": c} for s, c in top_skills],
    }


def _save_report(report: dict) -> None:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _REPORTS_DIR / f"{report['month']}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Monthly report saved: {path}")


def _format_report(report: dict) -> str:
    month_label = datetime.strptime(report["month"], "%Y-%m").strftime("%B %Y").capitalize()
    breakdown = report.get("rejection_breakdown", {})
    breakdown_lines = "".join(
        f"\n    • {k}: {v}x" for k, v in sorted(breakdown.items(), key=lambda x: -x[1])
    )
    skills_lines = "".join(
        f"\n    {i+1}. {s['skill']} ({s['count']}x)"
        for i, s in enumerate(report.get("top_skills", []))
    )
    salary_line = (
        f"\n💰 Salário médio estimado: R$ {report['avg_salary_offered']:,.0f}".replace(",", ".")
        if report.get("avg_salary_offered") else ""
    )

    return (
        f"📊 <b>Relatório Mensal — {month_label}</b>\n\n"
        f"✅ Candidaturas enviadas: <b>{report['applications']}</b>\n"
        f"🤝 Conexões feitas: <b>{report['connections']}</b>\n"
        f"❌ Vagas rejeitadas: <b>{report['rejections']}</b>\n"
        f"🎯 Taxa de match: <b>{report['match_rate_pct']}%</b>"
        f"{salary_line}\n\n"
        f"📋 <b>Motivos de rejeição:</b>{breakdown_lines or ' —'}\n\n"
        f"🔥 <b>Top 3 skills mais exigidas:</b>{skills_lines or ' —'}"
    )


def run_monthly_report() -> None:
    today = date.today()

    if today.day != 1:
        logger.info(f"Monthly report: today is day {today.day}, skipping (runs only on day 1)")
        return

    month_key = _month_key(today.year, today.month)
    report_path = _REPORTS_DIR / f"{month_key}.json"
    if report_path.exists():
        logger.info("Monthly report already sent this month, skipping")
        return

    # Report covers the previous month
    if today.month == 1:
        year, month = today.year - 1, 12
    else:
        year, month = today.year, today.month - 1

    logger.info(f"Generating monthly report for {_month_key(year, month)}...")
    report = generate_report(year, month)
    _save_report(report)
    send_telegram(_format_report(report))
    logger.info("Monthly report sent via Telegram")
