"""Migração one-shot dos .local/files/*.json para o Postgres.

Lê os arquivos JSON DIRETO do disco (os trackers já são backend-aware e, com
DATABASE_URL setado, leriam o PG vazio) e escreve nas tabelas/kv. Idempotente:
tabelas tipadas via replace_all, kv via upsert. Os JSON não são apagados."""

import json
from pathlib import Path

from src.config.settings import logger
from src.core.persistence.db import connection
from src.core.persistence.doc_repo import DocRepo
from src.core.persistence.keyed_repo import KeyedRepo

_FILES_DIR = Path(".local") / "files"

# ns kv -> arquivo JSON (doc inteiro)
_KV_FILES = {
    "form_answers": "form_answers.json",
    "saved_searches": "saved_searches.json",
    "engage_targets": "engage_targets.json",
    "last_urls": "last_urls.json",
    "posted_history": "posted_history.json",
    "followup_dms": "followup_dms.json",
}

_TYPED_TABLES = (
    "applied_jobs",
    "rejected_jobs",
    "engaged_posts",
    "profile_views",
    "ssi_history",
    "skills_gap",
    "connections_log",
    "goals",
)


def _read_json(name: str):
    path = _FILES_DIR / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning(f"Migrate: não consegui ler {path}")
        return None


def _keyed_from_dict(table: str, key_field: str, name: str) -> int:
    data = _read_json(name) or {}
    rows = [{key_field: k, **v} for k, v in data.items()]
    KeyedRepo(table, key_field).replace_all(rows)
    return len(rows)


def _snapshots(table: str, name: str) -> int:
    data = _read_json(name) or {}
    rows = data.get("snapshots", [])
    KeyedRepo(table, "date").replace_all(rows)
    return len(rows)


def migrate_json_to_pg() -> dict[str, int]:
    counts: dict[str, int] = {}

    counts["applied_jobs"] = _keyed_from_dict(
        "applied_jobs", "job_id", "applied_jobs.json"
    )
    counts["rejected_jobs"] = _keyed_from_dict(
        "rejected_jobs", "job_id", "rejected_jobs.json"
    )
    counts["skills_gap"] = _keyed_from_dict("skills_gap", "skill", "skills_gap.json")
    counts["profile_views"] = _snapshots("profile_views", "profile_views.json")
    counts["ssi_history"] = _snapshots("ssi_history", "ssi_history.json")

    # connections_log: {date: count} -> linhas
    cl = _read_json("connections_log.json") or {}
    KeyedRepo("connections_log", "date").replace_all(
        [{"date": d, "count": c} for d, c in cl.items()]
    )
    counts["connections_log"] = len(cl)

    # goals: {metric: int} -> linhas
    goals = _read_json("goals.json") or {}
    KeyedRepo("goals", "metric").replace_all(
        [{"metric": m, "target": int(t)} for m, t in goals.items()]
    )
    counts["goals"] = len(goals)

    # engaged_posts: {engaged:[...], self_author} -> tabela + kv meta
    engaged = _read_json("engaged_posts.json") or {}
    KeyedRepo("engaged_posts", "urn").replace_all(engaged.get("engaged", []))
    counts["engaged_posts"] = len(engaged.get("engaged", []))
    if engaged.get("self_author"):
        DocRepo("engaged_meta").save({"self_author": engaged["self_author"]})

    # kv docs (doc inteiro por ns)
    for ns, name in _KV_FILES.items():
        data = _read_json(name)
        if data is not None:
            DocRepo(ns, json_file=_FILES_DIR / name).save(data)
            counts[f"kv:{ns}"] = 1

    # weekly_reports: pasta de arquivos -> kv por week
    reports_dir = _FILES_DIR / "weekly_reports"
    wr = 0
    if reports_dir.is_dir():
        repo = DocRepo("weekly_reports", json_dir=reports_dir)
        for f in reports_dir.glob("*.json"):
            try:
                repo.put(f.stem, json.loads(f.read_text(encoding="utf-8")))
                wr += 1
            except Exception:
                logger.warning(f"Migrate: pulei relatório {f}")
    counts["kv:weekly_reports"] = wr

    logger.info(f"Migração concluída: {counts}")
    return counts


def table_counts() -> dict[str, int]:
    """Contagem de linhas por tabela tipada + por ns no kv_store."""
    out: dict[str, int] = {}
    with connection() as conn:
        for table in _TYPED_TABLES:
            row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
            out[table] = row[0] if row else 0
        rows = conn.execute(
            "SELECT ns, count(*) FROM kv_store GROUP BY ns ORDER BY ns"
        ).fetchall()
        for ns, n in rows:
            out[f"kv:{ns}"] = n
    return out
