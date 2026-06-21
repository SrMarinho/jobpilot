import json
from datetime import date
from pathlib import Path

from src.config.settings import logger
from src.core.persistence.db import is_db_enabled
from src.core.persistence.doc_repo import DocRepo
from src.core.persistence.keyed_repo import KeyedRepo
from src.core.use_cases.skills_tracker import load_skills


class ReportRepository:
    """All persistence access for reports: source data + saved report storage.

    Backend-aware: lê de JSON local ou Postgres conforme is_db_enabled(). O
    resto do report package trabalha com dicts/lists puros.
    """

    def __init__(self, files_dir: Path | None = None):
        self.files_dir = files_dir or (Path(".local") / "files")
        self.reports_dir = self.files_dir / "weekly_reports"

    # ── source data ──────────────────────────────────────────────
    def _load(self, name: str) -> dict:
        path = self.files_dir / name
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning(f"Could not parse {path}")
        return {}

    def _keyed(self, table: str, key_field: str, file_name: str) -> dict:
        if is_db_enabled():
            return {
                r[key_field]: {k: v for k, v in r.items() if k != key_field}
                for r in KeyedRepo(table, key_field).all()
            }
        return self._load(file_name)

    def applied(self) -> dict:
        return self._keyed("applied_jobs", "job_id", "applied_jobs.json")

    def rejected(self) -> dict:
        return self._keyed("rejected_jobs", "job_id", "rejected_jobs.json")

    def skills(self) -> dict:
        return load_skills()  # já é backend-aware

    def qa(self) -> dict:
        return DocRepo(
            "form_answers", json_file=self.files_dir / "form_answers.json"
        ).load()

    def connections_log(self) -> dict:
        if is_db_enabled():
            return {
                r["date"]: r["count"]
                for r in KeyedRepo("connections_log", "date").all()
            }
        return self._load("connections_log.json")

    def engaged(self) -> list:
        if is_db_enabled():
            return sorted(
                KeyedRepo("engaged_posts", "urn").all(),
                key=lambda r: r.get("ts") or "",
            )
        return self._load("engaged_posts.json").get("engaged", [])

    def autopost(self) -> dict:
        return DocRepo(
            "posted_history", json_file=self.files_dir / "posted_history.json"
        ).load()

    def followup(self) -> dict:
        return DocRepo(
            "followup_dms", json_file=self.files_dir / "followup_dms.json"
        ).load()

    # ── connections log (write) ──────────────────────────────────
    def add_connections(self, count: int) -> None:
        today = date.today().isoformat()
        if is_db_enabled():
            repo = KeyedRepo("connections_log", "date")
            current = self.connections_log().get(today, 0)
            repo.upsert({"date": today, "count": current + count})
            return
        path = self.files_dir / "connections_log.json"
        log = self.connections_log()
        log[today] = log.get(today, 0) + count
        self.files_dir.mkdir(exist_ok=True, parents=True)
        path.write_text(json.dumps(log, indent=2), encoding="utf-8")

    # ── saved reports ────────────────────────────────────────────
    def _reports(self) -> DocRepo:
        return DocRepo("weekly_reports", json_dir=self.reports_dir)

    def report_path(self, key: str) -> Path:
        return self.reports_dir / f"{key}.json"

    def report_exists(self, key: str) -> bool:
        return self._reports().exists(key)

    def load_saved_report(self, key: str) -> dict | None:
        return self._reports().get(key)

    def save_report(self, report: dict) -> None:
        self._reports().put(report["week"], report)
        logger.info(f"Weekly report saved: {report['week']}")
