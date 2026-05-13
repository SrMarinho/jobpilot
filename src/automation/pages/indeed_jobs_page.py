import re
from playwright.async_api import Page
from src.config.settings import logger


class IndeedJobsPage:
    def __init__(self, page: Page, url: str):
        self.page = page
        self.url = url

    async def get_job_cards(self):
        try:
            await self.page.wait_for_selector(".job_seen_beacon", timeout=10000)
            return await self.page.locator(".job_seen_beacon").all()
        except Exception:
            logger.info("No job cards found on page")
            return []

    async def get_card_job_id(self, card) -> str:
        try:
            jk = await card.get_attribute("data-jk")
            if jk:
                return jk
            link = card.locator("a[data-jk]")
            return await link.get_attribute("data-jk") or ""
        except Exception:
            return ""

    async def get_card_job_url(self, card) -> str:
        jk = await self.get_card_job_id(card)
        if jk:
            return f"https://br.indeed.com/viewjob?jk={jk}"
        try:
            link = card.locator("a.jcs-JobTitle, h2.jobTitle a")
            href = await link.get_attribute("href") or ""
            return href
        except Exception:
            return ""

    async def get_company_name(self) -> str:
        try:
            el = self.page.locator(
                "[data-testid='inlineHeader-companyName'], "
                "[data-testid='jobsearch-CompanyInfoContainer'] a, "
                "div.jobsearch-CompanyInfoContainer a"
            )
            return (await el.inner_text()).strip()
        except Exception:
            return ""

    async def get_job_title(self) -> str:
        try:
            el = self.page.locator(
                "h2.jobsearch-JobInfoHeader-title, "
                "[data-testid='jobsearch-JobInfoHeader-title'], "
                "div.jobsearch-JobInfoHeader-title-container h2"
            )
            await el.wait_for(timeout=10000)
            text = (await el.inner_text()).strip()
            for suffix in (" - job post", "- job post", " - oferta de emprego", "- oferta de emprego"):
                if text.endswith(suffix):
                    text = text[: -len(suffix)].strip()
                    break
            return text
        except Exception:
            return ""

    async def get_job_description(self) -> str:
        try:
            el = self.page.locator("#jobDescriptionText")
            await el.wait_for(timeout=5000)
            return (await el.inner_text()).strip()
        except Exception:
            return ""

    async def get_apply_btn(self):
        css_selectors = [
            "#indeedApplyButton",
            "button#indeedApplyButton",
            "button.indeed-apply-button",
            "[data-testid='indeedApplyButton']",
            "button.ia-IndeedApplyButton",
            "button[class*='IndeedApplyButton']",
            "div.jobsearch-IndeedApplyButton-newDesign button",
        ]
        for sel in css_selectors:
            try:
                btn = self.page.locator(sel)
                if await btn.is_visible(timeout=5000) and await btn.is_enabled():
                    logger.info(f"Found Indeed Apply button via {sel}")
                    return btn
            except Exception:
                continue
        try:
            btn = self.page.locator(
                "xpath=//button[contains(@class,'indeed-apply') or contains(@class,'IndeedApply')]"
            )
            if await btn.is_visible(timeout=2000) and await btn.is_enabled():
                logger.info("Found Indeed Apply button via class match")
                return btn
        except Exception:
            pass
        if await self._has_external_apply():
            logger.info("External apply detected (company site) — skipping (not Indeed Apply)")
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
                if any(k in joined for k in (
                    "site da empresa", "company site", "company website",
                    "external", "candidate-se no site", "aplicar no site",
                )):
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
