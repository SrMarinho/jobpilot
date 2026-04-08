import time
import random
import threading
from selenium.webdriver.remote.webdriver import WebDriver
from src.core.use_cases import ConnectionHandler
from src.automation.pages import PeopleSearchPage
from src.config.settings import logger

class ConnectionManager:
    def __init__(self, driver: WebDriver, url: str, max_pages: int = 100, start_page: int = 1, stop_event: threading.Event | None = None):
        self.driver = driver
        self.base_url = url
        self.max_pages = max_pages
        self.start_page = start_page
        self.stop_event = stop_event or threading.Event()
        self.searched_page = PeopleSearchPage(self.driver, url=self.base_url)
        self.connect_people = ConnectionHandler(self.searched_page, stop_event=self.stop_event)

    def run(self):
        for page in range(self.start_page, self.max_pages + 1):
            if self.stop_event.is_set():
                logger.info("Stop requested, halting connection manager")
                break

            url = self.base_url if page == 1 else f"{self.base_url}&page={page}"
            logger.info(f"Navigating to page {page}")
            self.driver.get(url)

            wait = random.uniform(3, 6)
            logger.info(f"Waiting {wait:.1f}s before processing page {page}...")
            time.sleep(wait)

            self.connect_people.run()

            if self.connect_people.limit_reached:
                break

        logger.info(f"Total connections sent: {self.connect_people.invite_sended}")
