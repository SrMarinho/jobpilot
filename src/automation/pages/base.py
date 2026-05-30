from abc import ABC, abstractmethod
from playwright.async_api import Page


class BaseJobsPage(ABC):
    """Interface for job board page objects."""

    def __init__(self, page: Page, url: str):
        self.page = page
        self.url = url

    @abstractmethod
    async def get_job_cards(self) -> list:
        """Return all job card elements on the current page."""

    @abstractmethod
    async def get_card_job_url(self, card) -> str | None:
        """Extract job URL from a card element."""

    @abstractmethod
    async def get_card_job_id(self, card) -> str:
        """Extract a unique job identifier from a card element."""

    @abstractmethod
    async def get_job_title(self) -> str:
        """Return the currently selected job's title."""

    @abstractmethod
    async def get_job_description(self) -> str:
        """Return the currently selected job's description."""

    @abstractmethod
    async def get_company_name(self) -> str:
        """Return the currently selected job's company name."""

    def next_page_url(self, base_url: str, page_num: int) -> str:
        """Build the URL for the next results page (override if needed)."""
        raise NotImplementedError
