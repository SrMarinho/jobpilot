import sys
from typing import Optional

import typer

from src.utils.logger import set_run_context


def _parse_sections(only: str | None, skip: str | None) -> set[str] | None:
    from src.core.use_cases.report.formatter import ALL_SECTIONS

    if only:
        requested = {s.strip() for s in only.split(",")}
        unknown = requested - set(ALL_SECTIONS)
        if unknown:
            print(f"Seções desconhecidas: {', '.join(sorted(unknown))}")
            print(f"Disponíveis: {', '.join(ALL_SECTIONS)}")
        return requested & set(ALL_SECTIONS)
    if skip:
        excluded = {s.strip() for s in skip.split(",")}
        return set(ALL_SECTIONS) - excluded
    return None


def run_report(
    week: Optional[str],
    prev: bool,
    year: Optional[int],
    telegram: bool,
    scheduled: bool,
    only: Optional[str],
    skip: Optional[str],
    image: bool,
) -> None:
    from src.core.use_cases.report import ReportService, WeekPeriod

    service = ReportService()
    sections = _parse_sections(only, skip)

    def _print(text: str):
        plain = service.formatter.to_plaintext(text)
        sys.stdout.buffer.write((plain + "\n").encode("utf-8", "replace"))

    if scheduled:
        service.run_scheduled(sections=sections)
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
        rendered = service.format_weekly(report, sections=sections)

    if image and not year:
        _send_image(report, rendered, telegram)
    else:
        if telegram:
            from src.utils.telegram import send_telegram

            send_telegram(rendered, topic="report")
        _print(rendered)


def _send_image(report: dict, text_fallback: str, send_tg: bool) -> None:
    import asyncio
    import tempfile
    from pathlib import Path
    from src.core.use_cases.report.image_renderer import render_report_png
    from src.utils.telegram import send_telegram, send_telegram_photo

    from src.core.use_cases.report.image_renderer import _ensure_chromium

    _ensure_chromium()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        out_path = Path(f.name)

    try:
        asyncio.run(render_report_png(report, out_path))
        caption = (
            f"Relatório Semanal — {report.get('week', '')}\n"
            f"Candidaturas: {report.get('applications', 0)} | "
            f"Conexões: {report.get('connections', 0)} | "
            f"Match: {report.get('match_rate_pct', 0)}%"
        )
        if send_tg:
            send_telegram_photo(out_path, caption, topic="report")
        else:
            sys.stdout.buffer.write(
                f"PNG gerado: {out_path}\n".encode("utf-8", "replace")
            )
    except Exception as e:
        sys.stdout.buffer.write(
            f"Erro ao gerar imagem: {e}\n".encode("utf-8", "replace")
        )
        if send_tg:
            send_telegram(text_fallback, topic="report")
    finally:
        try:
            out_path.unlink(missing_ok=True)
        except Exception:
            pass


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
        only: Optional[str] = typer.Option(
            None,
            "--only",
            metavar="SECTIONS",
            help="Comma-separated section names to include (e.g. summary,autopost,goals)",
        ),
        skip: Optional[str] = typer.Option(
            None,
            "--skip",
            metavar="SECTIONS",
            help="Comma-separated section names to exclude",
        ),
        image: bool = typer.Option(
            False,
            "--image",
            help="Render report as PNG image (weekly only; use --telegram to send)",
        ),
    ):
        """Generate and print weekly report (default: current week)."""
        set_run_context("report")
        run_report(week, prev, year, telegram, scheduled, only, skip, image)
