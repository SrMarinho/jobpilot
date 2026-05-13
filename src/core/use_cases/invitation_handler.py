import threading
from src.automation.pages.people_search_page import PeopleSearchPage
from src.config.settings import logger


class ConnectionHandler:
    def __init__(self, page: PeopleSearchPage, stop_event: threading.Event | None = None):
        self.page = page
        self.invite_sended = 0
        self.limit_reached = False
        self.stop_event = stop_event or threading.Event()

    async def run(self):
        skip_labels: set[str] = set()
        while True:
            btn_connect = await self.page.get_connect_btn(skip_labels=skip_labels)
            if not btn_connect:
                break
            if self.stop_event.is_set():
                logger.info("Stop requested, halting connection handler")
                return
            label = await btn_connect.get_attribute("aria-label") or await btn_connect.inner_text()
            try:
                await btn_connect.click()
            except Exception:
                if await self.page.is_invite_limit_reached():
                    logger.warning("LinkedIn invite limit reached. Stopping.")
                    self.limit_reached = True
                    return
                await self.page.close_modal()
                continue

            confirm_btn = await self.page.get_confirm_invitation_btn()
            if confirm_btn:
                if await self.page.requires_message():
                    logger.info("Connection requires message, skipping")
                    skip_labels.add(label)
                    await self.page.close_modal()
                    continue
                await confirm_btn.click()
                self.invite_sended += 1
                logger.info(f"Invitation sent ({self.invite_sended})")
            else:
                logger.info("Could not confirm invitation, trying next")
                skip_labels.add(label)
                await self.page.close_modal()
