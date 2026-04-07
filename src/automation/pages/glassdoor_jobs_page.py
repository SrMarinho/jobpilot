import re
import time
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.remote.webelement import WebElement
from src.config.settings import logger


class GlassdoorJobsPage:
    def __init__(self, driver: WebDriver, url: str):
        self.driver = driver
        self.url = url

    def close_modal(self) -> None:
        try:
            btn = self.driver.find_element(
                By.CSS_SELECTOR,
                '[class*=modal_Modal] button[class*=close], '
                '[class*=modal_Modal] button[class*=Close], '
                '[class*=modal_Modal] button[aria-label="Close"], '
                'button[data-test="modal-close-btn"]',
            )
            btn.click()
            logger.info("Glassdoor modal closed")
            time.sleep(0.5)
        except Exception:
            pass

    def get_job_cards(self) -> list[WebElement]:
        self.close_modal()
        try:
            WebDriverWait(self.driver, 10).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, 'li[data-test="jobListing"]')
            )
            return self.driver.find_elements(By.CSS_SELECTOR, 'li[data-test="jobListing"]')
        except Exception:
            logger.info("No job cards found on page")
            return []

    def get_job_title(self) -> str:
        try:
            el = WebDriverWait(self.driver, 10).until(
                lambda d: d.find_element(By.CSS_SELECTOR, '[data-test="job-title"]')
            )
            return el.text.strip()
        except Exception:
            return ""

    def get_job_description(self) -> str:
        try:
            el = WebDriverWait(self.driver, 5).until(
                lambda d: d.find_element(By.CSS_SELECTOR, '[class*=JobDetails_jobDescription]')
            )
            return el.text.strip()
        except Exception:
            return ""

    def get_apply_btn(self) -> WebElement | None:
        skip_phrases = ["site da empresa", "company site", "empresa parceira"]

        # Try known selectors
        for sel in ['[data-test="easyApply"]', '[data-test="applyButton"]',
                    'button[class*=apply]', 'button[class*=Apply]',
                    '[class*=EasyApply]', '[class*=easyApply]']:
            try:
                btns = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for btn in btns:
                    if not btn.is_displayed() or not btn.is_enabled():
                        continue
                    if any(p in btn.text.strip().lower() for p in skip_phrases):
                        continue
                    logger.info(f"Found apply button: '{btn.text.strip()}'")
                    return btn
            except Exception:
                pass

        # Text-based fallback
        try:
            btn = self.driver.find_element(
                By.XPATH,
                "//button[contains(normalize-space(),'Candidatura rápida') or "
                "contains(normalize-space(),'Candidatar-se agora') or "
                "contains(normalize-space(),'Easy Apply')]",
            )
            if btn.is_displayed() and btn.is_enabled():
                logger.info(f"Found apply button via text: '{btn.text.strip()}'")
                return btn
        except Exception:
            pass

        logger.info("No native apply button found")
        return None

    def get_card_job_id(self, card: WebElement) -> str | None:
        try:
            return card.get_attribute("data-jobid")
        except Exception:
            return None

    def next_page_url(self, base_url: str, page_num: int) -> str:
        if page_num == 1:
            return base_url
        # Glassdoor pagination: insert _IP{n} before .htm
        if re.search(r'_IP\d+\.htm', base_url):
            return re.sub(r'_IP\d+\.htm', f'_IP{page_num}.htm', base_url)
        return re.sub(r'\.htm', f'_IP{page_num}.htm', base_url)
