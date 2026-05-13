from playwright.async_api import Page
from src.config.settings import logger


class JobsSearchPage:
    def __init__(self, page: Page, url: str):
        self.page = page
        self.url = url

    async def get_job_cards(self):
        try:
            await self.page.wait_for_selector(".job-card-container", timeout=10000)
            return await self.page.locator(".job-card-container").all()
        except Exception:
            logger.info("No job cards found on page")
            return []

    async def get_card_job_url(self, card) -> str | None:
        try:
            job_id = await card.get_attribute("data-job-id")
            if job_id:
                return f"https://www.linkedin.com/jobs/view/{job_id}/"
            anchor = card.locator("a[href*='/jobs/view/']")
            href = await anchor.get_attribute("href") or ""
            return href.split("?")[0] if href else None
        except Exception:
            return None

    async def get_job_title(self) -> str:
        try:
            el = self.page.locator(
                ".job-details-jobs-unified-top-card__job-title h1, "
                ".jobs-unified-top-card__job-title h1, "
                "h1.t-24"
            )
            await el.wait_for(timeout=10000)
            return (await el.inner_text()).strip()
        except Exception:
            return ""

    async def get_company_name(self) -> str:
        try:
            el = self.page.locator(
                ".job-details-jobs-unified-top-card__company-name a, "
                ".jobs-unified-top-card__company-name a, "
                ".jobs-unified-top-card__subtitle-primary-grouping a, "
                ".job-details-jobs-unified-top-card__primary-description a"
            )
            return (await el.inner_text()).strip()
        except Exception:
            return ""

    async def get_job_description(self) -> str:
        try:
            el = self.page.locator("#job-details")
            await el.wait_for(timeout=5000)
            return (await el.inner_text()).strip()
        except Exception:
            return ""

    async def get_easy_apply_btn(self):
        try:
            btn = self.page.locator(
                "xpath=//button["
                "contains(@aria-label,'Easy Apply to') or "
                "(contains(@aria-label,'Candidatura simplificada') and not(contains(@aria-label,'Filtro')))"
                "]"
            )
            if await btn.is_visible() and await btn.is_enabled():
                return btn
        except Exception:
            pass
        return None
