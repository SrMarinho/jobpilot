from src.config.settings import logger
from src.utils.telegram import send_telegram

from .builder import ReportBuilder
from .formatter import ReportFormatter
from .period import WeekPeriod
from .repository import ReportRepository


class ReportService:
    """Orchestrates report generation, persistence, and delivery.

    The single entry point used by the CLI and other callers — wires the
    repository, builder, and formatter together.
    """

    def __init__(
        self,
        repo: ReportRepository | None = None,
        builder: ReportBuilder | None = None,
        formatter: ReportFormatter | None = None,
    ):
        self.repo = repo or ReportRepository()
        self.builder = builder or ReportBuilder(self.repo)
        self.formatter = formatter or ReportFormatter()

    # ── connections passthrough (used by connect flow) ───────────
    def save_connections(self, count: int) -> None:
        self.repo.add_connections(count)

    # ── weekly ───────────────────────────────────────────────────
    def build_weekly(self, period: WeekPeriod) -> dict:
        report = self.builder.weekly(period)
        self.repo.save_report(report)
        return report

    def format_weekly(self, report: dict, sections: set[str] | None = None) -> str:
        return self.formatter.weekly(report, sections=sections)

    # ── annual ───────────────────────────────────────────────────
    def build_annual(self, year: int) -> dict:
        report = self.builder.annual(year)
        self.repo.save_report(report)
        return report

    def format_annual(self, report: dict) -> str:
        return self.formatter.annual(report)

    # ── delivery ─────────────────────────────────────────────────
    def send_now(self, sections: set[str] | None = None) -> None:
        """Generate and Telegram-send the previous week's report (manual)."""
        period = WeekPeriod.previous_of_today()
        logger.info(f"Generating weekly report for {period.key}...")
        report = self.build_weekly(period)
        send_telegram(self.formatter.weekly(report, sections=sections))
        logger.info("Weekly report sent via Telegram")

    def run_scheduled(self, sections: set[str] | None = None) -> None:
        """Send the report only once per week (startup/scheduled use)."""
        period = WeekPeriod.previous_of_today()
        if self.repo.report_exists(period.key):
            logger.info(f"Weekly report for {period.key} already sent, skipping")
            return
        logger.info(f"Generating weekly report for {period.key}...")
        report = self.build_weekly(period)
        send_telegram(self.formatter.weekly(report, sections=sections))
        logger.info("Weekly report sent via Telegram")
