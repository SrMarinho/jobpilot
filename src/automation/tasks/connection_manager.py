import time
import random
import threading
from playwright.async_api import Page
from src.core.use_cases import ConnectionHandler
from src.automation.pages import PeopleSearchPage
from src.config.settings import logger


class ConnectionManager:
    def __init__(self, page: Page, url: str, max_pages: int = 100, start_page: int = 1, stop_event: threading.Event | None = None, on_page_change=None):
        self.page = page
        self.base_url = url
        self.max_pages = max_pages
        self.start_page = start_page
        self.stop_event = stop_event or threading.Event()
        self.on_page_change = on_page_change
        self.searched_page = PeopleSearchPage(self.page, url=self.base_url)
        self.connect_people = ConnectionHandler(self.searched_page, stop_event=self.stop_event)

    async def run(self):
        for page_num in range(self.start_page, self.max_pages + 1):
            if self.stop_event.is_set():
                logger.info("Stop requested, halting connection manager")
                break

            if self.on_page_change:
                self.on_page_change(page_num)

            url = self.base_url if page_num == 1 else f"{self.base_url}&page={page_num}"
            logger.info(f"Navigating to page {page_num}")
            await self.page.goto(url, wait_until="domcontentloaded")

            await self._wait_for_page_load(page_num)

            await self.connect_people.run()

            if self.connect_people.limit_reached:
                break

        logger.info(f"Total connections sent: {self.connect_people.invite_sended}")

    async def _wait_for_page_load(self, page_num: int):
        await self.page.wait_for_timeout(1500)
        try:
            await self.page.wait_for_function("document.readyState === 'complete'", timeout=5000)
        except Exception:
            pass

        loading_selectors = [
            "div.loader", "div.artdeco-loader", "[class*=loader]",
            "[class*=spinner]", "[class*=skeleton]", "[class*=ghost]",
        ]
        try:
            for sel in loading_selectors:
                loader = self.page.locator(sel)
                if await loader.is_visible(timeout=2000):
                    await loader.wait_for(state="hidden", timeout=8000)
        except Exception:
            pass

        if page_num > 1:
            await self.page.wait_for_timeout(2000)
        else:
            wait = random.uniform(3, 6)
            logger.info(f"Waiting {wait:.1f}s before processing page {page_num}...")
            await self.page.wait_for_timeout(int(wait * 1000))
