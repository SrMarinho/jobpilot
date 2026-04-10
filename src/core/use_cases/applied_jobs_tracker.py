import json
import re
from datetime import datetime
from pathlib import Path
from src.config.settings import logger
from src.utils.telegram import send_telegram

_FILES_DIR = Path("files")
APPLIED_JOBS_FILE = _FILES_DIR / "applied_jobs.json"
REJECTED_JOBS_FILE = _FILES_DIR / "rejected_jobs.json"


class AppliedJobsTracker:
    def __init__(self):
        self._applied: dict = self._load(APPLIED_JOBS_FILE)
        self._rejected: dict = self._load(REJECTED_JOBS_FILE)

    def _load(self, path: Path) -> dict:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_applied(self):
        APPLIED_JOBS_FILE.write_text(
            json.dumps(self._applied, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _save_rejected(self):
        REJECTED_JOBS_FILE.write_text(
            json.dumps(self._rejected, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _job_id(self, url: str) -> str:
        """Extract a stable job ID from URL. Tries common patterns, falls back to sanitized URL."""
        # Glassdoor synthetic: glassdoor://job/NNN
        match = re.search(r"glassdoor://job/(\d+)", url)
        if match:
            return f"gd_{match.group(1)}"
        # LinkedIn: currentJobId=123 or /jobs/view/123
        match = re.search(r"currentJobId=(\d+)|/jobs/view/(\d+)", url)
        if match:
            return match.group(1) or match.group(2)
        # Indeed: /viewjob?jk=abc123
        match = re.search(r"[?&]jk=([a-zA-Z0-9]+)", url)
        if match:
            return match.group(1)
        # Gupy: /jobs/NNN
        match = re.search(r"/jobs/(\d+)", url)
        if match:
            return match.group(1)
        return re.sub(r"[^a-z0-9]", "_", url.lower())[:80]

    def already_applied(self, job_url: str) -> bool:
        return self._job_id(job_url) in self._applied

    def already_rejected(self, job_url: str) -> bool:
        return self._job_id(job_url) in self._rejected

    def mark_applied(self, job_url: str, title: str, salary: int | None = None, company: str = ""):
        job_id = self._job_id(job_url)
        self._applied[job_id] = {
            "title": title,
            "company": company,
            "url": job_url,
            "applied_at": datetime.now().isoformat(),
            "salary_offered": salary,
        }
        self._save_applied()
        logger.info(f"Saved application: '{title}' at '{company}' (id={job_id})")

        salary_line = f"\n💰 Pretensão: R$ {salary:,.0f}".replace(",", ".") if salary else ""
        company_line = f"\n🏢 {company}" if company else ""
        send_telegram(
            f"✅ <b>Candidatura enviada!</b>\n"
            f"📋 {title}{company_line}{salary_line}\n"
            f"🔗 <a href='{job_url}'>Ver vaga</a>"
        )

    def mark_rejected(self, job_url: str, title: str, reason: str = ""):
        job_id = self._job_id(job_url)
        self._rejected[job_id] = {
            "title": title,
            "url": job_url,
            "rejected_at": datetime.now().isoformat(),
            "reason": reason,
        }
        self._save_rejected()
        logger.debug(f"Saved rejection: '{title}' (id={job_id})")
