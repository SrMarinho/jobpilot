import sys
from typing import Optional

import typer

from src.utils.logger import set_run_context


def run_report(
    week: Optional[str],
    prev: bool,
    year: Optional[int],
    telegram: bool,
    scheduled: bool,
) -> None:
    from src.core.use_cases.report import ReportService, WeekPeriod

    service = ReportService()

    def _print(text: str):
        plain = service.formatter.to_plaintext(text)
        sys.stdout.buffer.write((plain + "\n").encode("utf-8", "replace"))

    if scheduled:
        service.run_scheduled()
        return

    if year:
        report = service.build_annual(year)
        rendered = service.format_annual(report)
    else:
        if prev:
            period = WeekPeriod.previous_of_today()
        elif week:
            try:
                period = WeekPeriod.from_key(week)
            except (ValueError, IndexError):
                print("Invalid --week format. Use YYYY-Www (e.g. 2026-W25)")
                return
        else:
            period = WeekPeriod.current()
        report = service.build_weekly(period)
        rendered = service.format_weekly(report)

    if telegram:
        from src.utils.telegram import send_telegram

        send_telegram(rendered)
    _print(rendered)


def register_report_command(app: typer.Typer) -> None:
    @app.command()
    def report(
        week: Optional[str] = typer.Option(
            None,
            "--week",
            metavar="YYYY-Www",
            help="Specific week (e.g. 2026-W25)",
        ),
        prev: bool = typer.Option(False, "--prev", help="Report for the previous week"),
        year: Optional[int] = typer.Option(
            None,
            "--year",
            metavar="YYYY",
            help="Annual summary for the given year (e.g. 2026)",
        ),
        telegram: bool = typer.Option(
            False, "--telegram", help="Send report via Telegram in addition to printing"
        ),
        scheduled: bool = typer.Option(
            False,
            "--scheduled",
            help="Scheduled mode: send via Telegram only once per week",
        ),
    ):
        """Generate and print weekly report (default: current week)."""
        set_run_context("report")
        run_report(week, prev, year, telegram, scheduled)
