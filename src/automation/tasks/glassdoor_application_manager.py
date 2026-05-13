from src.automation.tasks.base_application_manager import BaseJobApplicationManager
from src.automation.pages.glassdoor_jobs_page import GlassdoorJobsPage
from src.core.use_cases.job_application_handler import JobApplicationHandler


class GlassdoorJobApplicationManager(BaseJobApplicationManager):
    site = "glassdoor"
    PAGE_SIZE = 60

    def _build_page(self, page, url):
        return GlassdoorJobsPage(page, url)

    async def _wait_for_job_cards(self, page_num: int) -> list:
        cards = await super()._wait_for_job_cards(page_num)
        if cards and hasattr(self.page_obj, "scroll_to_load"):
            await self.page_obj.scroll_to_load(target=self.PAGE_SIZE)
            cards = await self.page_obj.get_job_cards()
        return cards

    def _build_handler(self, page, resume: str):
        return JobApplicationHandler(page, resume=resume)

    def _next_page_url(self, page_num: int) -> str:
        return self.page_obj.next_page_url(self.base_url, page_num)

    async def _get_card_id(self, card) -> str:
        try:
            jid = await self.page_obj.get_card_job_id(card)
            if jid:
                return jid
        except Exception:
            pass
        try:
            return await card.get_attribute("data-job-id") or await card.get_attribute("data-id") or (await card.inner_text())[:80]
        except Exception:
            return ""

    async def _get_card_job_url(self, card, page_num: int, idx: int) -> str | None:
        try:
            jid = await self.page_obj.get_card_job_id(card)
        except Exception:
            jid = None
        return f"glassdoor://job/{jid}" if jid else f"glassdoor://p{page_num}-c{idx}"

    async def _get_apply_btn(self):
        return await self.page_obj.get_apply_btn()

    async def _submit_application(self, salary, title: str, description: str) -> bool:
        return await self.handler.submit_easy_apply(
            salary_expectation=salary,
            job_title=title,
            job_description=description,
            no_submit=self.no_submit,
        )
