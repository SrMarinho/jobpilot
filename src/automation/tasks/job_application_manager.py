import time
from selenium.webdriver.remote.webdriver import WebDriver
from src.automation.pages.jobs_search_page import JobsSearchPage
from src.core.use_cases.job_evaluator import JobEvaluator
from src.core.use_cases.job_application_handler import JobApplicationHandler
from src.config.settings import logger


class JobApplicationManager:
    PAGE_SIZE = 25

    def __init__(
        self,
        driver: WebDriver,
        url: str,
        resume_path: str,
        preferences: str = "",
        max_pages: int = 100,
    ):
        self.driver = driver
        self.base_url = url
        self.max_pages = max_pages
        self.page = JobsSearchPage(driver, url)
        self.evaluator = JobEvaluator(resume_path, preferences=preferences)
        self.handler = JobApplicationHandler(driver)
        self.applied_count = 0
        self.evaluated_count = 0

    def run(self):
        for page_num in range(1, self.max_pages + 1):
            start = self.PAGE_SIZE * (page_num - 1)
            url = self.base_url if page_num == 1 else f"{self.base_url}&start={start}"
            logger.info(f"Navigating to page {page_num}")
            self.driver.get(url)
            time.sleep(2)

            job_cards = self.page.get_job_cards()
            if not job_cards:
                logger.info("No more jobs found, stopping")
                break

            logger.info(f"Found {len(job_cards)} jobs on page {page_num}")
            self._process_jobs(job_cards)

        logger.info(
            f"Finished. Evaluated: {self.evaluated_count} | Applied: {self.applied_count}"
        )

    def _process_jobs(self, job_cards):
        for i, card in enumerate(job_cards):
            try:
                card.click()
                time.sleep(1.5)

                title = self.page.get_job_title()
                description = self.page.get_job_description()

                if not title or not description:
                    logger.info(f"Job {i + 1}: Could not extract details, skipping")
                    continue

                logger.info(f"Job {i + 1}: Evaluating '{title}'")
                self.evaluated_count += 1

                if not self.evaluator.evaluate(title, description):
                    logger.info(f"Job {i + 1}: Not a match, skipping")
                    continue

                easy_apply_btn = self.page.get_easy_apply_btn()
                if not easy_apply_btn:
                    logger.info(f"Job {i + 1}: No Easy Apply button, skipping")
                    continue

                logger.info(f"Job {i + 1}: Match! Applying to '{title}'")
                easy_apply_btn.click()
                time.sleep(1)

                if self.handler.submit_easy_apply():
                    self.applied_count += 1
                    logger.info(f"Applied ({self.applied_count} total)")

                time.sleep(1)

            except Exception as e:
                logger.error(f"Error on job {i + 1}: {e}")
