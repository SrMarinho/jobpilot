import time
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.remote.webelement import WebElement
from src.config.settings import logger


class PeopleSearchPage:
    def __init__(self, driver: WebDriver, url: str):
        self.driver = driver
        self.url = url

    def is_invite_limit_reached(self) -> bool:
        try:
            self.driver.find_element(By.CSS_SELECTOR, "[data-test-modal-id='fuse-limit-alert']")
            return True
        except Exception:
            return False

    def close_modal(self) -> None:
        try:
            btn: WebElement = WebDriverWait(self.driver, 5).until(
                lambda d: d.find_element(By.CSS_SELECTOR, "button[aria-label='Fechar']")
            )
            btn.click()
        except Exception:
            try:
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            except Exception:
                logger.error("No modal to close")

    def get_confirm_invitation_btn(self) -> WebElement | None:
        logger.info("Waiting for invitation modal")
        try:
            WebDriverWait(self.driver, 5).until(
                lambda d: d.find_element(By.CSS_SELECTOR, "[data-test-modal-container]")
            )
        except Exception:
            logger.error("No modal appeared after clicking Connect")
            return None

        # Check for "withdraw invite" modal (PT or EN)
        try:
            self.driver.find_element(
                By.XPATH,
                "//button[contains(@aria-label,'Retirar convite') or contains(@aria-label,'Withdraw')]"
            )
            logger.info("Withdraw invite modal detected, skipping")
            return None
        except Exception:
            pass

        # Look for "Send without note" button (PT or EN)
        for selector in [
            "button[aria-label='Enviar sem nota']",
            "button[aria-label='Send without a note']",
            "button[aria-label='Send now']",
        ]:
            try:
                btn: WebElement = self.driver.find_element(By.CSS_SELECTOR, selector)
                if btn.get_attribute("disabled"):
                    logger.info("Confirm button is disabled")
                    return None
                return btn
            except Exception:
                pass

        # Fallback: any button with "Send" or "Enviar" in the modal
        try:
            btn = self.driver.find_element(
                By.XPATH,
                "//*[@data-test-modal-container]//button[contains(normalize-space(),'Send') or contains(normalize-space(),'Enviar')]"
            )
            if not btn.get_attribute("disabled"):
                return btn
        except Exception as e:
            logger.error(f"Confirm button not found. {e}")
        return None

    def requires_message(self) -> bool:
        """Returns True if the open modal requires a message to connect."""
        try:
            self.driver.find_element(By.CSS_SELECTOR, "[data-test-modal-container] textarea")
            return True
        except Exception:
            return False

    def get_connect_btn(self, skip_labels: set[str] | None = None) -> WebElement | None:
        time.sleep(0.2)
        skip_labels = skip_labels or set()
        xpaths = [
            # PT-BR: "Convidar [Nome] para se conectar"
            "//button[contains(@aria-label,'Convidar') and contains(@aria-label,'conectar')]",
            # EN: "Connect with [Name]" or "Invite [Name] to connect"
            "//button[contains(@aria-label,'Connect with') or contains(@aria-label,'Invite') and contains(@aria-label,'connect')]",
            # Fallback: any visible button with text "Conectar" or "Connect"
            "//button[normalize-space()='Conectar' or normalize-space()='Connect']",
        ]
        for xpath in xpaths:
            try:
                btns = self.driver.find_elements(By.XPATH, xpath)
                for btn in btns:
                    if not btn.is_displayed() or not btn.is_enabled():
                        continue
                    label = btn.get_attribute("aria-label") or btn.text
                    if label in skip_labels:
                        logger.info(f"Skipping already-tried button: '{label}'")
                        continue
                    logger.info(f"Found connect button: '{label}'")
                    return btn
            except Exception:
                pass
        logger.info("No connect buttons found on page")
        return None
