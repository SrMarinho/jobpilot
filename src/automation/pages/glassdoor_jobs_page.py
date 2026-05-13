import re
from playwright.async_api import Page
from src.config.settings import logger


class GlassdoorJobsPage:
    def __init__(self, page: Page, url: str):
        self.page = page
        self.url = url

    async def close_modal(self) -> None:
        try:
            btn = self.page.locator(
                '[class*=modal_Modal] button[class*=close], '
                '[class*=modal_Modal] button[class*=Close], '
                '[class*=modal_Modal] button[aria-label="Close"], '
                'button[data-test="modal-close-btn"]'
            )
            if await btn.is_visible(timeout=2000):
                await btn.click()
                logger.info("Glassdoor modal closed")
        except Exception:
            pass

    async def get_job_cards(self):
        await self.close_modal()
        try:
            await self.page.wait_for_selector('li[data-test="jobListing"]', timeout=10000)
            return await self.page.locator('li[data-test="jobListing"]').all()
        except Exception:
            logger.info("No job cards found on page")
            return []

    async def scroll_to_load(self, target: int = 60, max_attempts: int = 10) -> int:
        last = len(await self.get_job_cards())
        plateau = 0
        for _ in range(max_attempts):
            if last >= target:
                break
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self.page.wait_for_timeout(1200)
            cur = len(await self.get_job_cards())
            if cur == last:
                plateau += 1
                if plateau >= 2:
                    break
            else:
                plateau = 0
            last = cur
        return last

    async def get_job_title(self) -> str:
        try:
            el = self.page.locator('[data-test="job-title"]')
            await el.wait_for(timeout=10000)
            return (await el.inner_text()).strip()
        except Exception:
            return ""

    async def get_job_description(self) -> str:
        try:
            el = self.page.locator('[class*=JobDetails_jobDescription]')
            await el.wait_for(timeout=5000)
            return (await el.inner_text()).strip()
        except Exception:
            return ""

    async def get_apply_btn(self):
        skip_phrases = ["site da empresa", "company site", "empresa parceira"]
        for sel in ['[data-test="easyApply"]', '[data-test="applyButton"]',
                    'button[class*=apply]', 'button[class*=Apply]',
                    '[class*=EasyApply]', '[class*=easyApply]']:
            try:
                btns = self.page.locator(sel)
                count = await btns.count()
                for i in range(count):
                    btn = btns.nth(i)
                    if not await btn.is_visible() or not await btn.is_enabled():
                        continue
                    text = (await btn.inner_text()).strip().lower()
                    if any(p in text for p in skip_phrases):
                        continue
                    logger.info(f"Found apply button: '{await btn.inner_text()}'")
                    return btn
            except Exception:
                pass
        try:
            btn = self.page.locator(
                "xpath=//button[contains(normalize-space(),'Candidatura rápida') or "
                "contains(normalize-space(),'Candidatar-se agora') or "
                "contains(normalize-space(),'Easy Apply')]"
            )
            if await btn.is_visible() and await btn.is_enabled():
                logger.info(f"Found apply button via text: '{await btn.inner_text()}'")
                return btn
        except Exception:
            pass
        logger.info("No native apply button found")
        return None

    async def get_card_job_id(self, card) -> str | None:
        try:
            return await card.get_attribute("data-jobid")
        except Exception:
            return None

    async def get_card_title(self, card) -> str:
        try:
            el = card.locator('[class*=JobCard_jobTitle], a[data-test="job-title"], [class*=jobTitle]')
            return (await el.inner_text()).strip()
        except Exception:
            return ""

    async def get_card_company(self, card) -> str:
        try:
            el = card.locator('[class*=EmployerProfile_employerName], [data-test="employer-name"], [class*=employerName]')
            return (await el.inner_text()).strip()
        except Exception:
            return ""

    def next_page_url(self, base_url: str, page_num: int) -> str:
        if page_num == 1:
            return base_url
        if re.search(r'_IP\d+\.htm', base_url):
            return re.sub(r'_IP\d+\.htm', f'_IP{page_num}.htm', base_url)
        return re.sub(r'\.htm', f'_IP{page_num}.htm', base_url)
