"""Ciclo de vida do modal do Easy Apply: abrir, esperar, inspecionar, fechar.

Todos os seletores do modal ficam aqui — antes estavam repetidos em cinco
métodos diferentes da classe monolítica, cada um com sua própria lista.
"""

from playwright.async_api import Locator, Page

from src.automation.pages.selectors import T_FAST, T_NORMAL, first_visible

# O modal do Easy Apply, em ordem de preferência.
MODAL = [
    "[data-test-modal-container]",
    "[class*=artdeco-modal]",
    "[role='dialog']",
]
_CLOSE_BUTTON = [
    "button[aria-label='Dismiss']",
    "button[aria-label='Close']",
    "button[aria-label='Fechar']",
    "button[data-test-modal-close-btn]",
]
_DISCARD_BUTTON = [
    "xpath=//button[contains(@aria-label,'Discard') or contains(normalize-space(),'Discard') or contains(normalize-space(),'Descartar')]"
]
_REVIEW_BUTTON = [
    "xpath=//button[contains(@aria-label,'Review') or contains(normalize-space(),'Review')]",
    "button[class*=review]",
    "button[type='submit']",
]
_FORM_ERROR = [
    "[aria-describedby*='error']",
    "[class*=error]",
    "[class*=feedback]",
    "[role='alert']",
]
# Elementos que costumam carregar o enunciado da pergunta dentro do modal.
_QUESTION_TEXT = "span, label, legend, p, div[class*=title], div[class*=heading]"
_MAX_QUESTION_PARTS = 20


class ModalDriver:
    def __init__(self, page: Page):
        self.page = page

    # ── Ciclo de vida ────────────────────────────────────────────────────────

    async def current(self) -> Locator:
        """Modal visível, ou ``body`` como escopo de fallback.

        Nunca devolve ``None``: o chamador sempre precisa de um escopo pra
        procurar campos, e o formulário pode estar fora de um modal.
        """
        modal = await first_visible(
            self.page, MODAL, field="easy apply modal", timeout=T_FAST, required=False
        )
        return modal if modal is not None else self.page.locator("body")

    async def wait_open(self, timeout_s: int = 15) -> bool:
        for selector in MODAL:
            try:
                await self.page.wait_for_selector(selector, timeout=timeout_s * 1000)
                return True
            except Exception:
                continue
        return False

    async def wait_closed(self, timeout_s: int = 10) -> bool:
        for selector in MODAL:
            try:
                await self.page.locator(selector).wait_for(
                    state="hidden", timeout=timeout_s * 1000
                )
                return True
            except Exception:
                continue
        return False

    async def close(self) -> None:
        """Fecha pelo botão; se não achar, Escape."""
        button = await first_visible(
            self.page,
            _CLOSE_BUTTON,
            field="modal close button",
            timeout=T_FAST,
            required=False,
        )
        if button is not None:
            try:
                await button.click()
                await self.page.wait_for_timeout(500)
                return
            except Exception:
                pass
        try:
            await self.page.keyboard.press("Escape")
            await self.page.wait_for_timeout(500)
        except Exception:
            pass

    # ── Descarte de rascunho ─────────────────────────────────────────────────

    async def has_discard_prompt(self) -> bool:
        return (
            await first_visible(
                self.page,
                _DISCARD_BUTTON,
                field="discard modal",
                timeout=T_FAST,
                required=False,
            )
            is not None
        )

    async def confirm_discard(self) -> None:
        button = await first_visible(
            self.page,
            _DISCARD_BUTTON,
            field="discard button",
            timeout=T_FAST,
            required=False,
        )
        if button is None:
            await self.page.keyboard.press("Escape")
            return
        try:
            await button.click()
            await self.page.wait_for_timeout(500)
        except Exception:
            await self.page.keyboard.press("Escape")

    # ── Inspeção ─────────────────────────────────────────────────────────────

    async def has_form_errors(self) -> bool:
        return (
            await first_visible(
                self.page,
                _FORM_ERROR,
                field="form error",
                timeout=T_FAST,
                required=False,
            )
            is not None
        )

    async def scroll_to_review(self) -> None:
        button = await first_visible(
            self.page,
            _REVIEW_BUTTON,
            field="review button",
            timeout=T_NORMAL,
            required=False,
        )
        if button is None:
            return
        try:
            await button.scroll_into_view_if_needed()
        except Exception:
            pass

    async def question_text(self) -> str:
        """Junta os textos visíveis do modal — o enunciado da etapa atual."""
        try:
            modal = await self.current()
            parts = modal.locator(_QUESTION_TEXT)
            count = min(await parts.count(), _MAX_QUESTION_PARTS)
            texts = []
            for i in range(count):
                text = (await parts.nth(i).inner_text()).strip()
                if text:
                    texts.append(text)
            return " | ".join(texts)
        except Exception:
            return ""

    async def options(self) -> list[str]:
        """Alternativas oferecidas na etapa atual (select, radio, labels)."""
        modal = await self.current()
        found: list[str] = []
        for selector in (
            "select option",
            "input[type='radio']",
            "label",
            "span.radio-label",
        ):
            try:
                elements = modal.locator(selector)
                for i in range(await elements.count()):
                    text = (await elements.nth(i).inner_text()).strip()
                    value = await elements.nth(i).get_attribute("value")
                    if text:
                        found.append(text)
                    elif value:
                        found.append(value)
            except Exception:
                continue
        if not found:
            try:
                select = modal.locator("select").first
                if await select.is_visible(timeout=500):
                    found = await select.locator("option").all_inner_texts()
            except Exception:
                pass
        # dict.fromkeys: dedup preservando a ordem de apresentação.
        return list(dict.fromkeys(o for o in found if o))
