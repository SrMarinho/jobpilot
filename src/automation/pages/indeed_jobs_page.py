import re
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
_CARDS = ".job_seen_beacon"
_TITLE = [
    "h2.jobsearch-JobInfoHeader-title",
    "[data-testid='jobsearch-JobInfoHeader-title']",
    "div.jobsearch-JobInfoHeader-title-container h2",
]
_COMPANY = [
    "[data-testid='inlineHeader-companyName']",
    "[data-testid='jobsearch-CompanyInfoContainer'] a",
    "div.jobsearch-CompanyInfoContainer a",
]
_DESCRIPTION = ["#jobDescriptionText"]
_APPLY_BTN = [
    "#indeedApplyButton",
    "button#indeedApplyButton",
    "button.indeed-apply-button",
    "[data-testid='indeedApplyButton']",
    "button.ia-IndeedApplyButton",
    "button[class*='IndeedApplyButton']",
    "div.jobsearch-IndeedApplyButton-newDesign button",
    "xpath=//button[contains(@class,'indeed-apply') or contains(@class,'IndeedApply')]",
]
# Sufixos que o Indeed cola no título e não fazem parte do cargo.
_TITLE_SUFFIXES = (
    " - job post",
    "- job post",
    " - oferta de emprego",
    "- oferta de emprego",
)
_EXTERNAL_APPLY_MARKERS = (
    "site da empresa",
    "company site",
    "company website",
    "external",
    "candidate-se no site",
    "aplicar no site",
)


class IndeedJobsPage(BaseJobsPage):
    async def get_job_cards(self):
        try:
            await self.page.wait_for_selector(_CARDS, timeout=T_SLOW)
            return await self.page.locator(_CARDS).all()
        except Exception:
            logger.info("No job cards found on page")
            return []

    async def get_card_job_id(self, card) -> str:
        try:
            jk = await card.get_attribute("data-jk")
            if jk:
                return jk
            link = card.locator("a[data-jk]").first
            return await link.get_attribute("data-jk") or ""
        except Exception:
            return ""

    async def get_card_job_url(self, card) -> str:
        jk = await self.get_card_job_id(card)
        if jk:
            return f"https://br.indeed.com/viewjob?jk={jk}"
        try:
            link = card.locator("a.jcs-JobTitle, h2.jobTitle a").first
            href = await link.get_attribute("href") or ""
            return href
        except Exception:
            return ""

    async def get_company_name(self) -> str:
        return await text_or_empty(
            self.page, _COMPANY, field="indeed company name", timeout=T_FAST
        )

    async def get_job_title(self) -> str:
        text = await text_or_empty(
            self.page, _TITLE, field="indeed job title", timeout=T_SLOW
        )
        for suffix in _TITLE_SUFFIXES:
            if text.endswith(suffix):
                return text[: -len(suffix)].strip()
        return text

    async def get_job_description(self) -> str:
        return await text_or_empty(
            self.page, _DESCRIPTION, field="indeed job description", timeout=T_NORMAL
        )

    async def get_apply_btn(self):
        # required=False: vaga com apply externo é caso normal, não quebra.
        btn = await first_enabled(
            self.page,
            _APPLY_BTN,
            field="indeed apply button",
            timeout=T_NORMAL,
            required=False,
        )
        if btn is not None:
            return btn
        if await self._has_external_apply():
            logger.info(
                "External apply detected (company site) — skipping (not Indeed Apply)"
            )
        else:
            logger.info("No Indeed Apply button found")
        return None

    async def _has_external_apply(self) -> bool:
        try:
            els = self.page.locator("xpath=//a | //button")
            count = await els.count()
            for i in range(count):
                el = els.nth(i)
                if not await el.is_visible():
                    continue
                txt = (await el.inner_text() or "").lower()
                aria = (await el.get_attribute("aria-label") or "").lower()
                joined = f"{txt} {aria}"
                if any(k in joined for k in _EXTERNAL_APPLY_MARKERS):
                    return True
        except Exception:
            pass
        return False

    def next_page_url(self, base_url: str, page_num: int, page_size: int = 50) -> str:
        start = (page_num - 1) * page_size
        url = base_url
        if "limit=" not in url:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}limit={page_size}"
        if "start=" in url:
            return re.sub(r"start=\d+", f"start={start}", url)
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}start={start}"
