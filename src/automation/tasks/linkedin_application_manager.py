from src.automation.tasks.base_application_manager import BaseJobApplicationManager
from src.automation.pages.jobs_search_page import JobsSearchPage
from src.core.use_cases.job_application_handler import JobApplicationHandler


class LinkedInJobApplicationManager(BaseJobApplicationManager):
    site = "linkedin"
    PAGE_SIZE = 25

    def _normalize_url(self, url: str) -> str:
        return url.replace("/jobs/search-results/", "/jobs/search/")

    def _build_page(self, page, url):
        return JobsSearchPage(page, url)

    def _build_handler(self, page, resume: str):
        return JobApplicationHandler(page, resume=resume)

    def _next_page_url(self, page_num: int) -> str:
        if page_num == 1:
            return self.base_url
        start = self.PAGE_SIZE * (page_num - 1)
        return f"{self.base_url}&start={start}"

    async def _get_card_id(self, card) -> str:
        try:
            url = await self.page_obj.get_card_job_url(card)
            if url:
                return url
        except Exception:
            pass
        try:
            return await card.get_attribute("data-job-id") or await card.get_attribute("data-id") or (await card.inner_text())[:80]
        except Exception:
            return ""

    async def _get_card_job_url(self, card, page_num: int, idx: int) -> str | None:
        try:
            return await self.page_obj.get_card_job_url(card)
        except Exception:
            return None

    async def _get_apply_btn(self):
        return await self.page_obj.get_easy_apply_btn()

    async def _submit_application(self, salary, title: str, description: str) -> bool:
        return await self.handler.submit_easy_apply(
            salary_expectation=salary,
            job_title=title,
            job_description=description,
            no_submit=self.no_submit,
        )
