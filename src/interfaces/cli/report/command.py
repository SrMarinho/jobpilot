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
    from datetime import date as _date
    from src.core.use_cases.weekly_report import (
        generate_report,
        generate_year_report,
        _save_report,
        _format_report,
        _format_year_report,
        _prev_week,
        _current_week,
        run_weekly_report_scheduled,
    )

    def _print(text: str):
        sys.stdout.buffer.write(
            (
                text.replace("<b>", "")
                .replace("</b>", "")
                .replace("<i>", "")
                .replace("</i>", "")
                + "\n"
            ).encode("utf-8", "replace")
        )

    if scheduled:
        run_weekly_report_scheduled()
    elif year:
        rep = generate_year_report(year)
        _save_report(rep)
        if telegram:
            from src.utils.telegram import send_telegram

            send_telegram(_format_year_report(rep))
        _print(_format_year_report(rep))
    else:
        today = _date.today()
        if prev:
            yr, wk = _prev_week(today)
        elif week:
            try:
                parts = week.upper().replace("W", "").split("-")
                yr, wk = int(parts[0]), int(parts[1])
            except (ValueError, IndexError):
                print("Invalid --week format. Use YYYY-Www (e.g. 2026-W25)")
                return
        else:
            yr, wk = _current_week(today)
        rep = generate_report(yr, wk)
        _save_report(rep)
        if telegram:
            from src.utils.telegram import send_telegram

            send_telegram(_format_report(rep))
        _print(_format_report(rep))


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
