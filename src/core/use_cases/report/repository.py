import json
from datetime import date
from pathlib import Path

from src.config.settings import logger


class ReportRepository:
    """All disk access for reports: source JSON files + saved report storage.

    Single place that knows file paths and (de)serialization — the rest of the
    report package works with plain dicts/lists.
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

    def applied(self) -> dict:
        return self._load("applied_jobs.json")

    def rejected(self) -> dict:
        return self._load("rejected_jobs.json")

    def skills(self) -> dict:
        return self._load("skills_gap.json")

    def qa(self) -> dict:
        return self._load("form_answers.json")

    def connections_log(self) -> dict:
        return self._load("connections_log.json")

    def engaged(self) -> list:
        return self._load("engaged_posts.json").get("engaged", [])

    def autopost(self) -> dict:
        return self._load("posted_history.json")

    def followup(self) -> dict:
        return self._load("followup_dms.json")

    # ── connections log (write) ──────────────────────────────────
    def add_connections(self, count: int) -> None:
        path = self.files_dir / "connections_log.json"
        log = self.connections_log()
        today = date.today().isoformat()
        log[today] = log.get(today, 0) + count
        self.files_dir.mkdir(exist_ok=True, parents=True)
        path.write_text(json.dumps(log, indent=2), encoding="utf-8")

    # ── saved reports ────────────────────────────────────────────
    def report_path(self, key: str) -> Path:
        return self.reports_dir / f"{key}.json"

    def report_exists(self, key: str) -> bool:
        return self.report_path(key).exists()

    def load_saved_report(self, key: str) -> dict | None:
        path = self.report_path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save_report(self, report: dict) -> None:
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        path = self.report_path(report["week"])
        path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"Weekly report saved: {path}")
