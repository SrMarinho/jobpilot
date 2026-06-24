from pathlib import Path

from src.config.settings import logger
from src.core.ai.llm_provider import get_eval_provider
from src.automation.tasks.hired_profile_manager import HiredProfileManager
from src.core.use_cases.exporter import export_hired_profiles_csv
from src.core.use_cases.resume_loader import load_resume_text
from src.core.use_cases.hired_report import (
    enrich_missing,
    format_aggregate,
    format_full_report,
    format_gap,
    format_trend,
    split_have_missing,
)
from src.interfaces.cli.persistence import _find_resume


def _strip_html(text: str) -> str:
    return text.replace("<b>", "").replace("</b>", "")


async def run_hired_browser(
    page,
    roles: list[str],
    days: int,
    max_profiles: int,
    dry_run: bool,
    out: str | None,
    gap: bool,
    resume: str | None,
    trend: bool,
    telegram: bool,
) -> None:
    provider = None if dry_run else get_eval_provider()
    if provider:
        logger.info(f"Using LLM for skill extraction: {provider.describe()}")

    tracker = None
    for role in roles:
        logger.info(f"[hired] coletando role: {role!r}")
        manager = HiredProfileManager(
            page,
            role=role,
            llm_provider=provider,
            days=days,
            max_profiles=max_profiles,
            dry_run=dry_run,
        )
        tracker = await manager.run()

    role_label = ", ".join(roles)
    aggregate = tracker.aggregate(role=roles, window_days=days)

    # ── gap vs currículo (computado uma vez) ──
    have: list[tuple[str, int]] = []
    missing_enriched: list[dict] = []
    if gap:
        resume_path = _find_resume(resume or "")
        resume_text = load_resume_text(resume_path)
        if not resume_text:
            logger.warning(f"Currículo vazio/não encontrado em {resume_path}")
        have, missing = split_have_missing(aggregate, resume_text)
        missing_enriched = await enrich_missing(missing)

    # ── tendência (computada uma vez) ──
    trend_rows = tracker.trend(role=roles) if trend else []

    # ── saída console ──
    print("\n" + _strip_html(format_aggregate(aggregate, role_label, days)))
    if gap:
        print("\n" + _strip_html(format_gap(have, missing_enriched)))
    if trend:
        print("\n" + _strip_html(format_trend(trend_rows)))

    # ── Telegram (relatório completo) ──
    if telegram:
        from src.utils.telegram import send_telegram

        report = format_full_report(
            aggregate, have, missing_enriched, trend_rows, role_label, days
        )
        send_telegram(report, topic="report")
        logger.info("Relatório 'hired' enviado via Telegram")

    if out:
        n = export_hired_profiles_csv(Path(out))
        logger.info(f"CSV exportado: {n} perfis → {out}")
