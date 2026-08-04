from typing import List

import typer

from src.config.settings import logger
from src.automation import url_builder as _url_builder
from src.automation.tasks.connection_manager import ConnectionManager
from src.core.use_cases.rate_limiter import RateLimiter
from src.core.use_cases.run_guard import check_run
from src.interfaces.cli.persistence import (
    load_last_urls,
    save_last_url,
    save_ran_today,
    save_weekly_limit_reached,
)


def resolve_connect_config(
    url: str | None,
    keywords: List[str] | None,
    network: str | None,
    start_page: int | None,
    resume: bool,
    scheduled: bool,
    rotate: bool = False,
) -> dict | None:
    """Resolve connect URL from args or saved state.  Returns None if should skip.

    Returns dict with keys: url, start_page, on_page_change.
    """
    last_urls = load_last_urls()
    site_key = "connect"
    saved: dict = last_urls.get(site_key, {})

    # ── guard do run (cooldown, janela horária, quota, já-rodou-hoje) ──
    verdict = check_run("connect", scheduled=scheduled)
    if not verdict:
        logger.info(f"Connect não vai rodar — {verdict.reason}")
        return None
    if scheduled:
        save_ran_today()

    # ── rotação de saved-searches ──
    if rotate and not url:
        from src.core.use_cases.saved_searches import SavedSearches

        nxt = SavedSearches().next("connect")
        if nxt and nxt.get("url"):
            url = nxt["url"]
            logger.info(f"Rotação connect: usando '{nxt.get('label')}'")
        else:
            logger.warning("--rotate sem buscas salvas; caindo para resolução normal")

    # ── URL resolution ──
    if url:
        resolved_url = url
        resolved_start_page = start_page or 1
    elif keywords:
        resolved_url = _url_builder.build_linkedin_people_url(keywords, network=network)
        resolved_start_page = start_page or 1
        print(
            f"Using search: keywords='{' '.join(keywords)}'"
            + (f", network={network}" if network else "")
        )
    else:
        saved_kw = saved.get("keywords") if isinstance(saved, dict) else None
        saved_keywords = saved_kw.split() if isinstance(saved_kw, str) else saved_kw
        if saved_keywords:
            resolved_url = _url_builder.build_linkedin_people_url(
                saved_keywords,
                network=saved.get("network"),
            )
        else:
            resolved_url = saved.get("url") if isinstance(saved, dict) else None
        if not resolved_url:
            print("Error: pass --url or --keywords for the first 'connect' run.")
            raise typer.Exit()

        if resume:
            resolved_start_page = saved.get("page", 1) if isinstance(saved, dict) else 1
            print(f"Resuming 'connect' from page {resolved_start_page}: {resolved_url}")
        else:
            resolved_start_page = start_page or 1
            print(f"Using last saved search for 'connect': {resolved_url}")

    # ── save initial config ──
    if resolved_url and (url or keywords or not saved.get("url")):
        extra = {}
        if keywords:
            extra["keywords"] = " ".join(keywords)
        if network:
            extra["network"] = network
        save_last_url(site_key, resolved_url, page=1, extra=extra if extra else None)

    # ── on_page_change callback ──
    final_network = network or (
        saved.get("network") if isinstance(saved, dict) else None
    )
    final_keywords_str = (
        " ".join(keywords)
        if keywords
        else (saved.get("keywords") if isinstance(saved, dict) else None)
    )

    def on_page_change(page: int):
        extra = {}
        if final_keywords_str:
            extra["keywords"] = final_keywords_str
        if final_network:
            extra["network"] = final_network
        save_last_url(site_key, resolved_url, page=page, extra=extra if extra else None)

    return {
        "url": resolved_url,
        "start_page": resolved_start_page,
        "on_page_change": on_page_change,
    }


async def run_connect_browser(
    page, url: str, max_pages: int, start_page: int, on_page_change
) -> None:
    from src.core.use_cases.report import ReportService

    manager = ConnectionManager(
        page,
        url=url,
        max_pages=max_pages,
        start_page=start_page,
        on_page_change=on_page_change,
    )
    await manager.run()
    sent = manager.connect_people.invite_sended
    if sent:
        ReportService().save_connections(sent)
    if manager.connect_people.limit_reached:
        save_weekly_limit_reached()
        logger.info("Weekly limit reached — saved. Will skip until next week.")
        # Chegar no limite do LinkedIn significa que a quota própria estava
        # frouxa demais: pausa os runs agendados até revisão manual.
        RateLimiter().open_cooldown("LinkedIn sinalizou limite de convites")
