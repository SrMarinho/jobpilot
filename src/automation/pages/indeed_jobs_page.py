import time
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.remote.webelement import WebElement
from src.config.settings import logger


class IndeedJobsPage:
    def __init__(self, driver: WebDriver, url: str):
        self.driver = driver
        self.url = url

    def get_job_cards(self) -> list[WebElement]:
        try:
            WebDriverWait(self.driver, 10).until(
                lambda d: d.find_elements(By.CSS_SELECTOR, ".job_seen_beacon")
            )
            return self.driver.find_elements(By.CSS_SELECTOR, ".job_seen_beacon")
        except Exception:
            logger.info("No job cards found on page")
            return []

    def get_card_job_id(self, card: WebElement) -> str:
        try:
            jk = card.get_attribute("data-jk")
            if jk:
                return jk
            link = card.find_element(By.CSS_SELECTOR, "a[data-jk]")
            return link.get_attribute("data-jk") or ""
        except Exception:
            return ""

    def get_card_job_url(self, card: WebElement) -> str:
        jk = self.get_card_job_id(card)
        if jk:
            return f"https://br.indeed.com/viewjob?jk={jk}"
        try:
            link = card.find_element(By.CSS_SELECTOR, "a.jcs-JobTitle, h2.jobTitle a")
            href = link.get_attribute("href") or ""
            return href
        except Exception:
            return ""

    def get_company_name(self) -> str:
        try:
            el = self.driver.find_element(
                By.CSS_SELECTOR,
                "[data-testid='inlineHeader-companyName'], "
                "[data-testid='jobsearch-CompanyInfoContainer'] a, "
                "div.jobsearch-CompanyInfoContainer a",
            )
            return el.text.strip()
        except Exception:
            return ""

    def get_job_title(self) -> str:
        try:
            el = WebDriverWait(self.driver, 10).until(
                lambda d: d.find_element(
                    By.CSS_SELECTOR,
                    "h2.jobsearch-JobInfoHeader-title, "
                    "[data-testid='jobsearch-JobInfoHeader-title'], "
                    "div.jobsearch-JobInfoHeader-title-container h2",
                )
            )
            text = el.text.strip()
            for suffix in (" - job post", "- job post", " - oferta de emprego", "- oferta de emprego"):
                if text.endswith(suffix):
                    text = text[: -len(suffix)].strip()
                    break
            return text
        except Exception:
            return ""

    def get_job_description(self) -> str:
        try:
            el = WebDriverWait(self.driver, 5).until(
                lambda d: d.find_element(By.ID, "jobDescriptionText")
            )
            return el.text.strip()
        except Exception:
            return ""

    def get_apply_btn(self) -> WebElement | None:
        css_selectors = [
            "#indeedApplyButton",
            "button#indeedApplyButton",
            "button.indeed-apply-button",
            "[data-testid='indeedApplyButton']",
            "button.ia-IndeedApplyButton",
            "button[class*='IndeedApplyButton']",
            "div#viewJobButtonLinkContainer button",
            "div.jobsearch-IndeedApplyButton-newDesign button",
        ]
        # Wait up to 5s for any selector to appear (right pane loads async)
        try:
            WebDriverWait(self.driver, 5).until(
                lambda d: any(
                    e.is_displayed() and e.is_enabled()
                    for sel in css_selectors
                    for e in d.find_elements(By.CSS_SELECTOR, sel)
                )
            )
        except Exception:
            pass
        for sel in css_selectors:
            try:
                els = self.driver.find_elements(By.CSS_SELECTOR, sel)
                for btn in els:
                    if btn.is_displayed() and btn.is_enabled():
                        logger.info(f"Found Indeed Apply button via {sel}")
                        return btn
            except Exception:
                continue

        try:
            btn = self.driver.find_element(
                By.XPATH,
                "//button[contains(@class,'indeed-apply') or contains(@class,'IndeedApply') or "
                "contains(@aria-label,'Candidatar') or contains(@aria-label,'Apply') or "
                "contains(normalize-space(),'Candidatar-se facilmente') or "
                "contains(normalize-space(),'Candidatar-se com perfil') or "
                "contains(normalize-space(),'Candidatar-se agora') or "
                "contains(normalize-space(),'Candidatar-se') or "
                "contains(normalize-space(),'Apply now') or "
                "contains(normalize-space(),'Easily apply')]",
            )
            if btn.is_displayed() and btn.is_enabled():
                logger.info("Found apply button via text/aria match")
                return btn
        except Exception:
            pass

        # External-only apply ("Aplicar no site da empresa") is not actionable here
        logger.info("No Indeed Apply button found (likely external application)")
        return None

    def next_page_url(self, base_url: str, page_num: int) -> str:
        start = (page_num - 1) * 10
        if "start=" in base_url:
            import re
            return re.sub(r"start=\d+", f"start={start}", base_url)
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}start={start}"
