from src.config.settings import logger
from src.automation.pages.base import BaseJobsPage
from src.automation.pages.selectors import (
    T_FAST,
    T_NORMAL,
    T_SLOW,
    first_enabled,
    text_or_empty,
)

# Candidatos por campo, em ordem de preferência (ver selectors.py).
_CARDS = ".job-card-container"
_TITLE = [
    ".job-details-jobs-unified-top-card__job-title h1",
    ".jobs-unified-top-card__job-title h1",
    "h1.t-24",
]
_COMPANY = [
    ".job-details-jobs-unified-top-card__company-name a",
    ".jobs-unified-top-card__company-name a",
    ".jobs-unified-top-card__subtitle-primary-grouping a",
    ".job-details-jobs-unified-top-card__primary-description a",
]
_DESCRIPTION = ["#job-details", ".jobs-description__content"]
_EASY_APPLY = [
    "xpath=//button["
    "contains(@aria-label,'Easy Apply to') or "
    "(contains(@aria-label,'Candidatura simplificada') and not(contains(@aria-label,'Filtro')))"
    "]"
]


class JobsSearchPage(BaseJobsPage):
    async def get_job_cards(self):
        try:
            await self.page.wait_for_selector(_CARDS, timeout=T_SLOW)
            return await self.page.locator(_CARDS).all()
        except Exception:
            logger.info("No job cards found on page")
            return []

    async def get_card_job_url(self, card) -> str | None:
        try:
            job_id = await card.get_attribute("data-job-id")
            if job_id:
                return f"https://www.linkedin.com/jobs/view/{job_id}/"
            anchor = card.locator("a[href*='/jobs/view/']").first
            href = await anchor.get_attribute("href") or ""
            return href.split("?")[0] if href else None
        except Exception:
            return None

    async def get_job_title(self) -> str:
        return await text_or_empty(
            self.page, _TITLE, field="linkedin job title", timeout=T_SLOW
        )

    async def get_company_name(self) -> str:
        return await text_or_empty(
            self.page, _COMPANY, field="linkedin company name", timeout=T_FAST
        )

    async def get_job_description(self) -> str:
        return await text_or_empty(
            self.page, _DESCRIPTION, field="linkedin job description", timeout=T_NORMAL
        )

    async def get_easy_apply_btn(self):
        # required=False: vaga sem Easy Apply é caso normal, não quebra de layout.
        return await first_enabled(
            self.page, _EASY_APPLY, field="easy apply button", required=False
        )
