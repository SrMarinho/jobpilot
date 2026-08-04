from playwright.async_api import Page
from src.config.settings import logger
from src.automation.pages.selectors import (
    T_FAST,
    T_NORMAL,
    first_enabled,
    first_visible,
)

# Candidatos por campo, em ordem de preferência (ver selectors.py).
_MODAL_CLOSE = [
    "button[aria-label='Fechar']",
    "button[aria-label='Dismiss']",
    "button[aria-label='Close']",
]
_WITHDRAW_MODAL = [
    "xpath=//button[contains(@aria-label,'Retirar convite') or contains(@aria-label,'Withdraw')]"
]
_SEND_INVITE = [
    "button[aria-label='Enviar sem nota']",
    "button[aria-label='Send without a note']",
    "button[aria-label='Send now']",
    # Fallback: qualquer botão de envio dentro do modal.
    "xpath=//*[@data-test-modal-container]//button[contains(normalize-space(),'Send') or contains(normalize-space(),'Enviar')]",
]


class PeopleSearchPage:
    def __init__(self, page: Page, url: str):
        self.page = page
        self.url = url

    async def is_invite_limit_reached(self) -> bool:
        try:
            await self.page.wait_for_selector(
                "[data-test-modal-id='fuse-limit-alert']", timeout=3000
            )
            return True
        except Exception:
            return False

    async def close_modal(self) -> None:
        btn = await first_visible(
            self.page,
            _MODAL_CLOSE,
            field="invite modal close",
            timeout=T_NORMAL,
            required=False,
        )
        if btn is not None:
            try:
                await btn.click()
                return
            except Exception:
                pass
        try:
            await self.page.keyboard.press("Escape")
        except Exception:
            logger.error("No modal to close")

    async def get_confirm_invitation_btn(self):
        logger.info("Waiting for invitation modal")
        try:
            await self.page.wait_for_selector(
                "[data-test-modal-container]", timeout=5000
            )
        except Exception:
            logger.error("No modal appeared after clicking Connect")
            return None

        # Modal de "retirar convite" (PT/EN): já convidamos essa pessoa, pula.
        withdraw = await first_visible(
            self.page,
            _WITHDRAW_MODAL,
            field="withdraw invite modal",
            timeout=T_FAST,
            required=False,
        )
        if withdraw is not None:
            logger.info("Withdraw invite modal detected, skipping")
            return None

        return await first_enabled(
            self.page, _SEND_INVITE, field="send invite button", timeout=T_FAST
        )

    async def requires_message(self) -> bool:
        try:
            await self.page.wait_for_selector(
                "[data-test-modal-container] textarea", timeout=3000
            )
            return True
        except Exception:
            return False

    async def get_connect_btn(self, skip_labels: set[str] | None = None):
        skip_labels = skip_labels or set()
        # LinkedIn renders Connect as <a>, Invite confirm modal as <button>.
        # Match both via self::button | self::a in xpath.
        xpaths = [
            "//*[(self::button or self::a) and contains(@aria-label,'Convidar') and contains(@aria-label,'conectar')]",
            "//*[(self::button or self::a) and (contains(@aria-label,'Connect with') or (contains(@aria-label,'Invite') and contains(@aria-label,'connect')))]",
            "//*[(self::button or self::a) and (normalize-space()='Conectar' or normalize-space()='Connect')]",
        ]
        for xpath in xpaths:
            try:
                btns = self.page.locator(f"xpath={xpath}")
                count = await btns.count()
                for i in range(count):
                    btn = btns.nth(i)
                    if not await btn.is_visible() or not await btn.is_enabled():
                        continue
                    label = (
                        await btn.get_attribute("aria-label") or await btn.inner_text()
                    )
                    if label in skip_labels:
                        logger.info(f"Skipping already-tried button: '{label}'")
                        continue
                    logger.info(f"Found connect button: '{label}'")
                    return btn
            except Exception:
                pass
        logger.info("No connect buttons found on page")
        return None
