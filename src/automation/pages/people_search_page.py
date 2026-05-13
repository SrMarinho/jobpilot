from playwright.async_api import Page
from src.config.settings import logger


class PeopleSearchPage:
    def __init__(self, page: Page, url: str):
        self.page = page
        self.url = url

    async def is_invite_limit_reached(self) -> bool:
        try:
            await self.page.wait_for_selector("[data-test-modal-id='fuse-limit-alert']", timeout=3000)
            return True
        except Exception:
            return False

    async def close_modal(self) -> None:
        try:
            btn = self.page.locator("button[aria-label='Fechar']")
            await btn.wait_for(timeout=5000)
            await btn.click()
        except Exception:
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                logger.error("No modal to close")

    async def get_confirm_invitation_btn(self):
        logger.info("Waiting for invitation modal")
        try:
            await self.page.wait_for_selector("[data-test-modal-container]", timeout=5000)
        except Exception:
            logger.error("No modal appeared after clicking Connect")
            return None

        # Check for "withdraw invite" modal (PT or EN)
        try:
            withdraw = self.page.locator(
                "xpath=//button[contains(@aria-label,'Retirar convite') or contains(@aria-label,'Withdraw')]"
            )
            if await withdraw.is_visible(timeout=2000):
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
                btn = self.page.locator(selector)
                if await btn.is_visible(timeout=1000) and await btn.is_enabled():
                    return btn
            except Exception:
                pass

        # Fallback: any button with "Send" or "Enviar" in the modal
        try:
            btn = self.page.locator(
                "xpath=//*[@data-test-modal-container]//button[contains(normalize-space(),'Send') or contains(normalize-space(),'Enviar')]"
            )
            if await btn.is_visible(timeout=1000) and await btn.is_enabled():
                return btn
        except Exception as e:
            logger.error(f"Confirm button not found. {e}")
        return None

    async def requires_message(self) -> bool:
        try:
            await self.page.wait_for_selector("[data-test-modal-container] textarea", timeout=3000)
            return True
        except Exception:
            return False

    async def get_connect_btn(self, skip_labels: set[str] | None = None):
        skip_labels = skip_labels or set()
        xpaths = [
            "//button[contains(@aria-label,'Convidar') and contains(@aria-label,'conectar')]",
            "//button[contains(@aria-label,'Connect with') or contains(@aria-label,'Invite') and contains(@aria-label,'connect')]",
            "//button[normalize-space()='Conectar' or normalize-space()='Connect']",
        ]
        for xpath in xpaths:
            try:
                btns = self.page.locator(f"xpath={xpath}")
                count = await btns.count()
                for i in range(count):
                    btn = btns.nth(i)
                    if not await btn.is_visible() or not await btn.is_enabled():
                        continue
                    label = await btn.get_attribute("aria-label") or await btn.inner_text()
                    if label in skip_labels:
                        logger.info(f"Skipping already-tried button: '{label}'")
                        continue
                    logger.info(f"Found connect button: '{label}'")
                    return btn
            except Exception:
                pass
        logger.info("No connect buttons found on page")
        return None
