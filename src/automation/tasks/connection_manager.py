import time
import random
import threading
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.common.by import By
from src.core.use_cases import ConnectionHandler
from src.automation.pages import PeopleSearchPage
from src.config.settings import logger

class ConnectionManager:
    def __init__(self, driver: WebDriver, url: str, max_pages: int = 100, start_page: int = 1, stop_event: threading.Event | None = None, on_page_change=None):
        self.driver = driver
        self.base_url = url
        self.max_pages = max_pages
        self.start_page = start_page
        self.stop_event = stop_event or threading.Event()
        self.on_page_change = on_page_change
        self.searched_page = PeopleSearchPage(self.driver, url=self.base_url)
        self.connect_people = ConnectionHandler(self.searched_page, stop_event=self.stop_event)

    def run(self):
        for page in range(self.start_page, self.max_pages + 1):
            if self.stop_event.is_set():
                logger.info("Stop requested, halting connection manager")
                break

            if self.on_page_change:
                self.on_page_change(page)

            url = self.base_url if page == 1 else f"{self.base_url}&page={page}"
            logger.info(f"Navigating to page {page}")
            self.driver.get(url)

            self._wait_for_page_load(page)

            self.connect_people.run()

            if self.connect_people.limit_reached:
                break

        logger.info(f"Total connections sent: {self.connect_people.invite_sended}")

    def _wait_for_page_load(self, page_num: int):
        time.sleep(1.5)
        try:
            WebDriverWait(self.driver, 5).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except Exception:
            pass

        loading_selectors = [
            "div.loader", "div.artdeco-loader", "[class*=loader]",
            "[class*=spinner]", "[class*=skeleton]", "[class*=ghost]",
        ]
        try:
            WebDriverWait(self.driver, 8).until_not(
                lambda d: any(
                    e.is_displayed()
                    for sel in loading_selectors
                    for e in d.find_elements(By.CSS_SELECTOR, sel)
                )
            )
        except Exception:
            pass

        if page_num > 1:
            time.sleep(2)
        else:
            wait = random.uniform(3, 6)
            logger.info(f"Waiting {wait:.1f}s before processing page {page_num}...")
            time.sleep(wait)
