"""Export de dados do JobPilot para formatos externos.

Hoje: CSV (Excel/Sheets/Notion importam direto). Lê os JSONs de runtime
(applied/rejected) e escreve um CSV achatado. Notion/Sheets via API ficam
para depois — o CSV já cobre tracking externo e partilha.
"""

import csv
import json
from pathlib import Path

from src.config.settings import logger

_FILES_DIR = Path(".local") / "files"

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
    path = _FILES_DIR / name
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


def export_rejected_csv(out: Path) -> int:
    data = _load("rejected_jobs.json")
    rows = [{"job_id": jid, **v} for jid, v in data.items() if isinstance(v, dict)]
    rows.sort(key=lambda r: r.get("rejected_at", ""), reverse=True)
    n = _write_csv(rows, _REJECTED_FIELDS, out)
    logger.info(f"Exported {n} rejected jobs → {out}")
    return n
