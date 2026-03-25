import time
from selenium.webdriver.remote.webdriver import WebDriver
from src.automation.pages.jobs_search_page import JobsSearchPage
from src.core.use_cases.job_evaluator import JobEvaluator
from src.core.use_cases.job_application_handler import JobApplicationHandler
from src.core.use_cases.salary_estimator import SalaryEstimator
from src.core.use_cases.applied_jobs_tracker import AppliedJobsTracker
from src.config.settings import logger


class JobApplicationManager:
    PAGE_SIZE = 25

    def __init__(
        self,
        driver: WebDriver,
        url: str,
        resume_path: str,
        preferences: str = "",
        level: str = "",
        max_pages: int = 100,
    ):
        self.driver = driver
        self.base_url = url
        self.max_pages = max_pages
        self.page = JobsSearchPage(driver, url)
        self.evaluator = JobEvaluator(resume_path, preferences=preferences, level=level)
        self.salary_estimator = SalaryEstimator(resume=self.evaluator.resume)
        self.handler = JobApplicationHandler(driver, resume=self.evaluator.resume)
        self.tracker = AppliedJobsTracker()
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
        count = len(job_cards)
        for i in range(count):
            try:
                # Re-fetch cards each iteration to avoid stale element references
                cards = self.page.get_job_cards()
                if i >= len(cards):
                    break
                cards[i].click()
                time.sleep(1.5)

                job_url = self.driver.current_url
                title = self.page.get_job_title()
                description = self.page.get_job_description()

                if not title or not description:
                    logger.info(f"Job {i + 1}: Could not extract details, skipping")
                    continue

                if self.tracker.already_applied(job_url):
                    logger.info(f"Job {i + 1}: Already applied to '{title}', skipping")
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

                salary = self.salary_estimator.estimate(title, description)
                logger.info(f"Job {i + 1}: Match! Applying to '{title}'")
                easy_apply_btn.click()
                time.sleep(1)

                if self.handler.submit_easy_apply(salary_expectation=salary):
                    self.applied_count += 1
                    self.tracker.mark_applied(job_url, title, salary)
                    logger.info(f"Applied ({self.applied_count} total)")

                time.sleep(1)

            except Exception as e:
                logger.error(f"Error on job {i + 1}: {e}")
