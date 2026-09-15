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
_INVITE_MODAL = [
    "[data-test-modal-container]",
    "[role='dialog']",
    "[role='alertdialog']",
    ".artdeco-modal",
]
# Estado pós-convite. O LinkedIn 2026 envia boa parte dos convites direto, sem
# abrir modal nenhum: o botão vira "Pendente". Sem contar isso, o run enviava
# convites de verdade e reportava "Total connections sent: 0" — foi assim a
# semana toda de 08/09 a 14/09.
_PENDING_XPATH = (
    "xpath=//*[self::button or self::span or self::a]"
    "[normalize-space()='Pendente' or normalize-space()='Pending']"
)
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

    async def _head_text(self, limit: int = 200) -> str:
        """Head do innerText, só para diagnóstico em WARNING."""
        import re

        try:
            text = await self.page.evaluate("() => document.body.innerText || ''")
        except Exception:
            return "?"
        return re.sub(r"\s+", " ", text).strip()[:limit]

    async def pending_count(self) -> int:
        """Quantos botões estão em estado 'Pendente' na página agora."""
        try:
            return await self.page.locator(_PENDING_XPATH).count()
        except Exception:
            return 0

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
        modal = await first_visible(
            self.page,
            _INVITE_MODAL,
            field="invite modal",
            timeout=T_NORMAL,
            required=False,
        )
        if modal is None:
            # Sem modal pode ser layout novo (nenhum candidato casou) ou o
            # LinkedIn recusando o convite. Só o segundo caso é falha de
            # plataforma — o primeiro é bug nosso e não deve abrir o breaker.
            if await self.is_invite_limit_reached():
                logger.error("Limite de convites atingido")
            else:
                logger.warning(
                    "campo=invite modal: nenhum candidato casou após o Connect "
                    f"— selector pode ter mudado; página: {await self._head_text()!r}"
                )
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
