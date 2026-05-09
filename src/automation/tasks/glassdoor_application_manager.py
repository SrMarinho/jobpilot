from src.automation.tasks.base_application_manager import BaseJobApplicationManager
from src.automation.pages.glassdoor_jobs_page import GlassdoorJobsPage
from src.core.use_cases.job_application_handler import JobApplicationHandler


class GlassdoorJobApplicationManager(BaseJobApplicationManager):
    site = "glassdoor"
    PAGE_SIZE = 60

    def _build_page(self, driver, url):
        return GlassdoorJobsPage(driver, url)

    def _wait_for_job_cards(self, page_num: int) -> list:
        cards = super()._wait_for_job_cards(page_num)
        if cards and hasattr(self.page, "scroll_to_load"):
            self.page.scroll_to_load(target=self.PAGE_SIZE)
            cards = self.page.get_job_cards()
        return cards

    def _build_handler(self, driver, resume: str):
        return JobApplicationHandler(driver, resume=resume)

    def _next_page_url(self, page_num: int) -> str:
        return self.page.next_page_url(self.base_url, page_num)

    def _get_card_id(self, card) -> str:
        try:
            jid = self.page.get_card_job_id(card)
            if jid:
                return jid
        except Exception:
            pass
        try:
            return card.get_attribute("data-job-id") or card.get_attribute("data-id") or card.text[:80]
        except Exception:
            return ""

    def _get_card_job_url(self, card, page_num: int, idx: int) -> str | None:
        try:
            jid = self.page.get_card_job_id(card)
        except Exception:
            jid = None
        return f"glassdoor://job/{jid}" if jid else f"glassdoor://p{page_num}-c{idx}"

    def _get_apply_btn(self):
        return self.page.get_apply_btn()

    def _submit_application(self, salary, title: str, description: str) -> bool:
        return self.handler.submit_easy_apply(
            salary_expectation=salary,
            job_title=title,
            job_description=description,
            no_submit=self.no_submit,
        )
