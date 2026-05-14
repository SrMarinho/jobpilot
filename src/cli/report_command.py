from typing import Optional

import typer

from src.utils.logger import set_run_context
from src.cli.report_logic import run_report


def register_report_command(app: typer.Typer) -> None:
    @app.command()
    def report(
        month: Optional[str] = typer.Option(None, "--month", metavar="YYYY-MM", help="Specific month (e.g. 2025-03)"),
        prev: bool = typer.Option(False, "--prev", help="Report for the previous month"),
        year: Optional[int] = typer.Option(None, "--year", metavar="YYYY", help="Annual summary for the given year (e.g. 2026)"),
        telegram: bool = typer.Option(False, "--telegram", help="Send report via Telegram in addition to printing"),
        scheduled: bool = typer.Option(False, "--scheduled", help="Scheduled mode: send via Telegram only once per month"),
    ):
        """Generate and print monthly report (default: current month)."""
        set_run_context("report")
        run_report(month, prev, year, telegram, scheduled)
