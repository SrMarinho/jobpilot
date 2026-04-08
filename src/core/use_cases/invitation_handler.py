import time
import threading
from selenium.common.exceptions import ElementClickInterceptedException
from src.automation.pages.people_search_page import PeopleSearchPage
from src.config.settings import logger


class ConnectionHandler:
    def __init__(self, page: PeopleSearchPage, stop_event: threading.Event | None = None):
        self.page = page
        self.invite_sended = 0
        self.limit_reached = False
        self.stop_event = stop_event or threading.Event()

    def run(self):
        skip_labels: set[str] = set()
        while btn_connect := self.page.get_connect_btn(skip_labels=skip_labels):
            if self.stop_event.is_set():
                logger.info("Stop requested, halting connection handler")
                return
            label = btn_connect.get_attribute("aria-label") or btn_connect.text
            try:
                btn_connect.click()
            except ElementClickInterceptedException:
                if self.page.is_invite_limit_reached():
                    logger.warning("LinkedIn invite limit reached. Stopping.")
                    self.limit_reached = True
                    return
                self.page.close_modal()
                continue

            btn_confirm = self.page.get_confirm_invitation_btn()
            if not btn_confirm:
                if self.page.is_invite_limit_reached():
                    logger.warning("LinkedIn invite limit reached. Stopping.")
                    self.limit_reached = True
                    return
                logger.info(f"Skipping person (disabled or requires message): '{label}'")
                skip_labels.add(label)
                self.page.close_modal()
                continue

            btn_confirm.click()
            self.invite_sended += 1
            time.sleep(1)
