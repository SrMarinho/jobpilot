import src.config.settings as setting
from src.config.settings import logger
from src.automation.tasks.connection_manager import ConnectionManager
from src.cli.persistence import save_weekly_limit_reached


async def run_connect_browser(page, url: str, max_pages: int, start_page: int, on_page_change) -> None:
    from src.core.use_cases.monthly_report import save_connections
    manager = ConnectionManager(
        page, url=url,
        max_pages=max_pages, start_page=start_page,
        on_page_change=on_page_change,
    )
    await manager.run()
    sent = manager.connect_people.invite_sended
    if sent:
        save_connections(sent)
    if manager.connect_people.limit_reached:
        save_weekly_limit_reached()
        logger.info("Weekly limit reached — saved. Will skip until next week.")
    try:
        await page.screenshot(path=f"{setting.screenshots_path}.png")
    except Exception:
        pass
