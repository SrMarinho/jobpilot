"""Export de dados do JobPilot para formatos externos.

Hoje: CSV (Excel/Sheets/Notion importam direto). Lê os JSONs de runtime
(applied/rejected) e escreve um CSV achatado. Notion/Sheets via API ficam
para depois — o CSV já cobre tracking externo e partilha.
"""

import csv
import json
from pathlib import Path

from src.config.settings import files_dir, logger


_APPLIED_FIELDS = [
    "job_id",
    "title",
    "company",
    "level",
    "site",
    "contract",
    "salary_offered",
    "applied_at",
    "url",
]
_REJECTED_FIELDS = ["job_id", "title", "site", "reason", "rejected_at", "url"]


def _load(name: str) -> dict:
    path = files_dir / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning(f"Could not parse {path}")
        return {}


def _write_csv(rows: list[dict], fields: list[str], out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)


def export_applied_csv(out: Path) -> int:
    data = _load("applied_jobs.json")
    rows = [{"job_id": jid, **v} for jid, v in data.items() if isinstance(v, dict)]
    rows.sort(key=lambda r: r.get("applied_at", ""), reverse=True)
    n = _write_csv(rows, _APPLIED_FIELDS, out)
    logger.info(f"Exported {n} applied jobs → {out}")
    return n


_HIRED_FIELDS = [
    "name",
    "headline",
    "company",
    "top_skills",
    "age_days",
    "role",
    "source",
    "scraped_at",
    "profile_url",
]


def export_hired_profiles_csv(out: Path) -> int:
    data = _load("hired_profiles.json")
    profiles = data.get("profiles", []) if isinstance(data, dict) else []
    rows = []
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        row = dict(profile)
        skills = row.get("top_skills")
        if isinstance(skills, list):
            row["top_skills"] = "; ".join(skills)
        rows.append(row)
    rows.sort(key=lambda r: r.get("scraped_at", ""), reverse=True)
    n = _write_csv(rows, _HIRED_FIELDS, out)
    logger.info(f"Exported {n} hired profiles → {out}")
    return n


def export_rejected_csv(out: Path) -> int:
    data = _load("rejected_jobs.json")
    rows = [{"job_id": jid, **v} for jid, v in data.items() if isinstance(v, dict)]
    rows.sort(key=lambda r: r.get("rejected_at", ""), reverse=True)
    n = _write_csv(rows, _REJECTED_FIELDS, out)
    logger.info(f"Exported {n} rejected jobs → {out}")
    return n
