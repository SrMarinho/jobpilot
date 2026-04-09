import time
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.remote.webelement import WebElement
from src.config.settings import logger


class JobsSearchPage:
    def __init__(self, driver: WebDriver, url: str):
        self.driver = driver
        self.url = url

    def get_job_cards(self) -> list[WebElement]:
        try:
            WebDriverWait(self.driver, 10).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, ".job-card-container")
            )
            return self.driver.find_elements(By.CSS_SELECTOR, ".job-card-container")
        except Exception:
            logger.info("No job cards found on page")
            return []

    def get_card_job_url(self, card: WebElement) -> str | None:
        """Extract the job URL from the card element before clicking it."""
        try:
            # Try data-job-id attribute first (most reliable)
            job_id = card.get_attribute("data-job-id")
            if job_id:
                return f"https://www.linkedin.com/jobs/view/{job_id}/"
            # Fallback: href from first anchor inside the card
            anchor = card.find_element(By.CSS_SELECTOR, "a[href*='/jobs/view/']")
            href = anchor.get_attribute("href") or ""
            # Strip query params to keep the URL stable
            return href.split("?")[0] if href else None
        except Exception:
            return None

    def get_job_title(self) -> str:
        try:
            el = WebDriverWait(self.driver, 10).until(
                lambda d: d.find_element(
                    By.CSS_SELECTOR,
                    ".job-details-jobs-unified-top-card__job-title h1, "
                    ".jobs-unified-top-card__job-title h1, "
                    "h1.t-24",
                )
            )
            return el.text.strip()
        except Exception:
            return ""

    def get_job_description(self) -> str:
        try:
            el = WebDriverWait(self.driver, 5).until(
                lambda d: d.find_element(By.ID, "job-details")
            )
            return el.text.strip()
        except Exception:
            return ""

    def get_easy_apply_btn(self) -> WebElement | None:
        try:
            btn = self.driver.find_element(
                By.XPATH,
                "//button["
                "contains(@aria-label,'Easy Apply to') or "
                "(contains(@aria-label,'Candidatura simplificada') and not(contains(@aria-label,'Filtro')))"
                "]",
            )
            if btn.is_displayed() and btn.is_enabled():
                return btn
        except Exception:
            pass
        return None
