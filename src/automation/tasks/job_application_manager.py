import time
import threading
from selenium.webdriver.remote.webdriver import WebDriver
from src.automation.pages.jobs_search_page import JobsSearchPage
from src.automation.pages.indeed_jobs_page import IndeedJobsPage
from src.automation.pages.glassdoor_jobs_page import GlassdoorJobsPage
from src.core.use_cases.job_evaluator import JobEvaluator
from src.core.use_cases.job_application_handler import JobApplicationHandler
from src.core.use_cases.indeed_application_handler import IndeedApplicationHandler
from src.core.use_cases.salary_estimator import SalaryEstimator
from src.core.use_cases.applied_jobs_tracker import AppliedJobsTracker
from src.config.settings import logger


def _detect_site(url: str) -> str:
    if "indeed.com" in url:
        return "indeed"
    if "glassdoor.com" in url:
        return "glassdoor"
    return "linkedin"


def _normalize_url(url: str, site: str) -> str:
    if site == "linkedin":
        return url.replace("/jobs/search-results/", "/jobs/search/")
    return url


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
        stop_event: threading.Event | None = None,
    ):
        self.driver = driver
        self.base_url = url
        self.max_pages = max_pages
        self.site = _detect_site(url)
        self.base_url = _normalize_url(url, self.site)

        if self.site == "indeed":
            self.page = IndeedJobsPage(driver, url)
            self.PAGE_SIZE = 10
        elif self.site == "glassdoor":
            self.page = GlassdoorJobsPage(driver, url)
            self.PAGE_SIZE = 30
        else:
            self.page = JobsSearchPage(driver, url)

        self.evaluator = JobEvaluator(resume_path, preferences=preferences, level=level)
        self.salary_estimator = SalaryEstimator(resume=self.evaluator.resume)
        self.tracker = AppliedJobsTracker()
        self.stop_event = stop_event or threading.Event()
        self.applied_count = 0
        self.evaluated_count = 0

        if self.site == "indeed":
            self.handler = IndeedApplicationHandler(driver, resume=self.evaluator.resume)
        else:
            self.handler = JobApplicationHandler(driver, resume=self.evaluator.resume)

    def run(self):
        logger.info(f"Site detected: {self.site}")
        for page_num in range(1, self.max_pages + 1):
            if self.stop_event.is_set():
                logger.info("Stop requested, halting job application manager")
                break
            if self.site in ("indeed", "glassdoor"):
                url = self.page.next_page_url(self.base_url, page_num)
            else:
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
            if self.stop_event.is_set():
                logger.info("Stop requested, halting job processing")
                return
            try:
                cards = self.page.get_job_cards()
                if i >= len(cards):
                    break
                card = cards[i]
                if hasattr(self.page, 'close_modal'):
                    self.page.close_modal()
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
                time.sleep(0.3)

                # Read job_url BEFORE clicking (card element may go stale after click)
                if self.site == "glassdoor" and hasattr(self.page, "get_card_job_id"):
                    job_id = self.page.get_card_job_id(card)
                    job_url = f"glassdoor://job/{job_id}" if job_id else None
                else:
                    job_url = None

                try:
                    card.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", card)
                time.sleep(1.5)

                if not job_url:
                    job_url = self.driver.current_url
                title = self.page.get_job_title()
                description = self.page.get_job_description()

                if not title or not description:
                    logger.info(f"Job {i + 1}: Could not extract details, skipping")
                    continue

                if self.tracker.already_applied(job_url):
                    logger.info(f"Job {i + 1}: Already applied to '{title}', skipping")
                    continue

                if self.tracker.already_rejected(job_url):
                    logger.info(f"Job {i + 1}: Already rejected '{title}', skipping")
                    continue

                logger.info(f"Job {i + 1}: Evaluating '{title}'")
                self.evaluated_count += 1

                if not self.evaluator.evaluate(title, description):
                    logger.info(f"Job {i + 1}: Not a match, skipping")
                    self.tracker.mark_rejected(job_url, title, reason="AI evaluation: no match")
                    continue

                apply_btn = self.page.get_apply_btn() if self.site in ("indeed", "glassdoor") else self.page.get_easy_apply_btn()
                if not apply_btn:
                    logger.info(f"Job {i + 1}: No apply button, skipping")
                    continue

                salary = self.salary_estimator.estimate(title, description)
                logger.info(f"Job {i + 1}: Match! Applying to '{title}'")
                apply_btn.click()
                time.sleep(1.5)

                if self.site == "indeed":
                    success = self.handler.submit(salary_expectation=salary)
                else:
                    success = self.handler.submit_easy_apply(salary_expectation=salary)

                if success:
                    self.applied_count += 1
                    self.tracker.mark_applied(job_url, title, salary)
                    logger.info(f"Applied ({self.applied_count} total)")

                time.sleep(1)

            except Exception as e:
                logger.error(f"Error on job {i + 1}: {e}")
