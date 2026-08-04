import re
from src.config.settings import logger
from src.automation.pages.base import BaseJobsPage
from src.automation.pages.selectors import (
    T_FAST,
    T_NORMAL,
    T_SLOW,
    first_visible,
    text_or_empty,
)

# Candidatos por campo, em ordem de preferência (ver selectors.py).
_CARDS = 'li[data-test="jobListing"]'
_MODAL_CLOSE = [
    "[class*=modal_Modal] button[class*=close]",
    "[class*=modal_Modal] button[class*=Close]",
    '[class*=modal_Modal] button[aria-label="Close"]',
    'button[data-test="modal-close-btn"]',
]
_TITLE = ['[data-test="job-title"]']
_DESCRIPTION = ["[class*=JobDetails_jobDescription]"]
_CARD_TITLE = [
    "[class*=JobCard_jobTitle]",
    'a[data-test="job-title"]',
    "[class*=jobTitle]",
]
_CARD_COMPANY = [
    "[class*=EmployerProfile_employerName]",
    '[data-test="employer-name"]',
    "[class*=employerName]",
]
_APPLY_BTN = [
    '[data-test="easyApply"]',
    '[data-test="applyButton"]',
    "button[class*=apply]",
    "button[class*=Apply]",
    "[class*=EasyApply]",
    "[class*=easyApply]",
]
_APPLY_BTN_BY_TEXT = [
    "xpath=//button[contains(normalize-space(),'Candidatura rápida') or "
    "contains(normalize-space(),'Candidatar-se agora') or "
    "contains(normalize-space(),'Easy Apply')]"
]
# Botões que levam pro site da empresa, não pro apply nativo.
_EXTERNAL_APPLY_PHRASES = ("site da empresa", "company site", "empresa parceira")


class GlassdoorJobsPage(BaseJobsPage):
    async def close_modal(self) -> None:
        # required=False: normalmente não há modal — ausência não é quebra.
        btn = await first_visible(
            self.page,
            _MODAL_CLOSE,
            field="glassdoor modal close",
            timeout=T_FAST,
            required=False,
        )
        if btn is None:
            return
        try:
            await btn.click()
            logger.info("Glassdoor modal closed")
        except Exception:
            pass

    async def get_job_cards(self):
        await self.close_modal()
        try:
            await self.page.wait_for_selector(_CARDS, timeout=T_SLOW)
            return await self.page.locator(_CARDS).all()
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
        return await text_or_empty(
            self.page, _TITLE, field="glassdoor job title", timeout=T_SLOW
        )

    async def get_job_description(self) -> str:
        return await text_or_empty(
            self.page, _DESCRIPTION, field="glassdoor job description", timeout=T_NORMAL
        )

    async def get_apply_btn(self):
        """Botão de apply nativo, ignorando os que levam pro site da empresa.

        Não usa ``first_enabled`` porque aqui a escolha depende do TEXTO do
        botão: um mesmo seletor casa tanto o apply nativo quanto o link externo.
        """
        for sel in _APPLY_BTN:
            try:
                btns = self.page.locator(sel)
                for i in range(await btns.count()):
                    btn = btns.nth(i)
                    if not await btn.is_visible() or not await btn.is_enabled():
                        continue
                    text = (await btn.inner_text()).strip().lower()
                    if any(p in text for p in _EXTERNAL_APPLY_PHRASES):
                        continue
                    logger.info(f"Found apply button: '{text}'")
                    return btn
            except Exception:
                continue
        btn = await first_visible(
            self.page,
            _APPLY_BTN_BY_TEXT,
            field="glassdoor apply button",
            timeout=T_FAST,
            required=False,
        )
        if btn is not None:
            logger.info("Found apply button via text")
            return btn
        logger.info("No native apply button found")
        return None

    async def get_card_job_id(self, card) -> str | None:
        try:
            return await card.get_attribute("data-jobid")
        except Exception:
            return None

    async def get_card_title(self, card) -> str:
        return await text_or_empty(
            card, _CARD_TITLE, field="glassdoor card title", timeout=T_FAST
        )

    async def get_card_company(self, card) -> str:
        return await text_or_empty(
            card, _CARD_COMPANY, field="glassdoor card company", timeout=T_FAST
        )

    def next_page_url(self, base_url: str, page_num: int) -> str:
        if page_num == 1:
            return base_url
        if re.search(r"_IP\d+\.htm", base_url):
            return re.sub(r"_IP\d+\.htm", f"_IP{page_num}.htm", base_url)
        return re.sub(r"\.htm", f"_IP{page_num}.htm", base_url)
