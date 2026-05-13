from src.automation.tasks.base_application_manager import BaseJobApplicationManager
from src.automation.pages.indeed_jobs_page import IndeedJobsPage
from src.core.use_cases.indeed_application_handler import IndeedApplicationHandler


class IndeedJobApplicationManager(BaseJobApplicationManager):
    site = "indeed"
    PAGE_SIZE = 50

    def _build_page(self, page, url):
        return IndeedJobsPage(page, url)

    def _build_handler(self, page, resume: str):
        return IndeedApplicationHandler(page, resume=resume)

    def _next_page_url(self, page_num: int) -> str:
        return self.page_obj.next_page_url(self.base_url, page_num, page_size=self.PAGE_SIZE)

    async def _get_card_id(self, card) -> str:
        try:
            jk = await self.page_obj.get_card_job_id(card)
            if jk:
                return jk
        except Exception:
            pass
        try:
            return await card.get_attribute("data-job-id") or await card.get_attribute("data-id") or (await card.inner_text())[:80]
        except Exception:
            return ""

    async def _get_card_job_url(self, card, page_num: int, idx: int) -> str | None:
        try:
            return await self.page_obj.get_card_job_url(card) or None
        except Exception:
            return None

    async def _get_apply_btn(self):
        btn = await self.page_obj.get_apply_btn()
        if btn is None and await self.page_obj._has_external_apply():
            self._last_skip_reason = "Quick reject: external apply (não é candidatura rápida)"
        else:
            self._last_skip_reason = None
        return btn

    async def _submit_application(self, salary, title: str, description: str) -> bool:
        return await self.handler.submit(salary_expectation=salary, no_submit=self.no_submit)
