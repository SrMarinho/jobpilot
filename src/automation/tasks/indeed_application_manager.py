from src.automation.tasks.base_application_manager import BaseJobApplicationManager
from src.automation.pages.indeed_jobs_page import IndeedJobsPage
from src.core.use_cases.indeed_application_handler import IndeedApplicationHandler


class IndeedJobApplicationManager(BaseJobApplicationManager):
    site = "indeed"
    PAGE_SIZE = 50

    def _build_page(self, driver, url):
        return IndeedJobsPage(driver, url)

    def _build_handler(self, driver, resume: str):
        return IndeedApplicationHandler(driver, resume=resume)

    def _next_page_url(self, page_num: int) -> str:
        return self.page.next_page_url(self.base_url, page_num, page_size=self.PAGE_SIZE)

    def _get_card_id(self, card) -> str:
        try:
            jk = self.page.get_card_job_id(card)
            if jk:
                return jk
        except Exception:
            pass
        try:
            return card.get_attribute("data-job-id") or card.get_attribute("data-id") or card.text[:80]
        except Exception:
            return ""

    def _get_card_job_url(self, card, page_num: int, idx: int) -> str | None:
        try:
            return self.page.get_card_job_url(card) or None
        except Exception:
            return None

    def _get_apply_btn(self):
        btn = self.page.get_apply_btn()
        if btn is None and self.page._has_external_apply():
            # Mark so we don't re-process: real rejection reason for stats
            self._last_skip_reason = "Quick reject: external apply (não é candidatura rápida)"
        else:
            self._last_skip_reason = None
        return btn

    def _submit_application(self, salary, title: str, description: str) -> bool:
        # Indeed handler runs in a popup tab; no_submit semantics applied inside.
        return self.handler.submit(salary_expectation=salary, no_submit=self.no_submit)
