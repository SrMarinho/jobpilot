import time
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import NoSuchElementException
from src.config.settings import logger


class JobApplicationHandler:
    MAX_STEPS = 10

    def __init__(self, driver: WebDriver):
        self.driver = driver

    def submit_easy_apply(self) -> bool:
        try:
            for _ in range(self.MAX_STEPS):
                time.sleep(1)

                if self._try_submit():
                    return True

                if self._has_unanswered_required_fields():
                    logger.warning("Required fields not filled — skipping")
                    self._close_modal()
                    return False

                if not self._click_next():
                    self._close_modal()
                    return False

            logger.warning("Exceeded max steps in Easy Apply flow")
            self._close_modal()
            return False

        except Exception as e:
            logger.error(f"Error during Easy Apply: {e}")
            self._close_modal()
            return False

    def _try_submit(self) -> bool:
        try:
            btn = self.driver.find_element(
                By.XPATH,
                "//button[contains(@aria-label,'Submit application') or "
                ".//span[text()='Submit application'] or "
                ".//span[text()='Enviar candidatura']]",
            )
            btn.click()
            logger.info("Application submitted")
            time.sleep(1.5)
            self._close_modal()
            return True
        except NoSuchElementException:
            return False

    def _click_next(self) -> bool:
        try:
            btn = self.driver.find_element(
                By.XPATH,
                "//button[contains(@aria-label,'Continue to next step') or "
                ".//span[text()='Next'] or "
                ".//span[text()='Próximo'] or "
                ".//span[text()='Review']]",
            )
            btn.click()
            return True
        except NoSuchElementException:
            logger.warning("No next or submit button found")
            return False

    def _has_unanswered_required_fields(self) -> bool:
        try:
            inputs = self.driver.find_elements(
                By.XPATH, "//input[@required and @type!='hidden']"
            )
            for inp in inputs:
                if not inp.get_attribute("value"):
                    return True

            selects = self.driver.find_elements(By.XPATH, "//select[@required]")
            for sel in selects:
                if not sel.get_attribute("value"):
                    return True
        except Exception:
            pass
        return False

    def _close_modal(self) -> None:
        try:
            btn = self.driver.find_element(
                By.XPATH,
                "//button[@aria-label='Dismiss' or @aria-label='Fechar' or "
                "contains(@class,'artdeco-modal__dismiss')]",
            )
            btn.click()
            time.sleep(0.5)
        except NoSuchElementException:
            try:
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            except Exception:
                pass
            return

        try:
            discard_btn = self.driver.find_element(
                By.XPATH,
                "//button[.//span[text()='Discard'] or .//span[text()='Descartar']]",
            )
            discard_btn.click()
        except NoSuchElementException:
            pass
