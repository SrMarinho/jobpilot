import sys
from typing import Optional


def run_report(
    month: Optional[str],
    prev: bool,
    year: Optional[int],
    telegram: bool,
    scheduled: bool,
) -> None:
    from datetime import date as _date
    from src.core.use_cases.monthly_report import (
        generate_report, generate_year_report, _save_report,
        _format_report, _format_year_report, _prev_month,
        run_monthly_report_scheduled,
    )

    def _print(text: str):
        sys.stdout.buffer.write((text.replace("<b>", "").replace("</b>", "") + "\n").encode("utf-8", "replace"))

    if scheduled:
        run_monthly_report_scheduled()
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
            yr, mo = _prev_month(today)
        elif month:
            try:
                yr, mo = map(int, month.split("-"))
            except ValueError:
                print("Invalid --month format. Use YYYY-MM")
                return
        else:
            yr, mo = today.year, today.month
        rep = generate_report(yr, mo)
        _save_report(rep)
        if telegram:
            from src.utils.telegram import send_telegram
            send_telegram(_format_report(rep))
        _print(_format_report(rep))
