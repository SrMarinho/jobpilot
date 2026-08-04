"""Page object: envia um DM para um perfil do LinkedIn.

Abre o perfil, clica em "Mensagem", digita e envia. Selectors best-effort
(aria-label PT/EN + fallback JS) — ⚠️ não verificado ao vivo.
"""

from playwright.async_api import Page

from src.config.settings import logger
from src.utils.pacing import type_like_human

_MESSAGE_BTN_JS = """
() => {
    const isVisible = (b) => {
        const r = b.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    };
    const nodes = document.querySelectorAll("button, a[role='button'], div[role='button']");
    for (const n of nodes) {
        if (!isVisible(n)) continue;
        const al = (n.getAttribute('aria-label') || '').toLowerCase();
        const txt = (n.innerText || '').trim().toLowerCase();
        if (/^mensagem$|enviar mensagem|^message$|message /.test(al + ' ' + txt)) {
            return n;
        }
    }
    return null;
}
"""

_SEND_BTN_JS = """
() => {
    const isVisible = (b) => {
        const r = b.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    };
    const btns = document.querySelectorAll("button");
    for (const b of btns) {
        if (b.disabled || !isVisible(b)) continue;
        const al = (b.getAttribute('aria-label') || '').toLowerCase();
        const txt = (b.innerText || '').trim().toLowerCase();
        if (txt === 'enviar' || txt === 'send' || /enviar mensagem|send message/.test(al)) {
            return b;
        }
    }
    return null;
}
"""


class MessagingPage:
    def __init__(self, page: Page):
        self.page = page

    async def _safe_click(self, handle, what: str) -> bool:
        elem = handle.as_element()
        if not elem:
            logger.warning(f"{what} não encontrado")
            return False
        try:
            await elem.click(timeout=5000)
            return True
        except Exception:
            try:
                await elem.evaluate("el => el.click()")
                return True
            except Exception as e:
                logger.warning(f"click em {what} falhou: {e}")
                return False

    async def _find_message_editor(self):
        for _ in range(12):
            editors = await self.page.query_selector_all(
                "[contenteditable='true'][role='textbox']"
            )
            for ed in editors:
                try:
                    al = (await ed.get_attribute("aria-label") or "").lower()
                    if "mensagem" in al or "message" in al or "escreva" in al:
                        if await ed.is_visible():
                            return ed
                except Exception:
                    continue
            await self.page.wait_for_timeout(300)
        # fallback: qualquer editor visível
        for ed in await self.page.query_selector_all("[contenteditable='true']"):
            try:
                if await ed.is_visible():
                    return ed
            except Exception:
                continue
        return None

    async def send_dm(self, profile_url: str, text: str) -> bool:
        from src.automation.checkpoint import ensure_not_blocked

        logger.info(f"Abrindo perfil p/ DM: {profile_url}")
        await self.page.goto(profile_url, wait_until="domcontentloaded")
        await ensure_not_blocked(self.page, "followup_dm")
        await self.page.wait_for_timeout(2500)

        msg_handle = await self.page.evaluate_handle(_MESSAGE_BTN_JS)
        if not await self._safe_click(msg_handle, "botão Mensagem"):
            return False
        await self.page.wait_for_timeout(2000)

        editor = await self._find_message_editor()
        if not editor:
            logger.warning("Editor de mensagem não visível")
            return False
        try:
            await editor.click()
            await self.page.wait_for_timeout(300)
            await type_like_human(editor, text)
            await self.page.wait_for_timeout(800)
        except Exception as e:
            logger.warning(f"Digitar DM falhou: {e}")
            return False

        send_handle = await self.page.evaluate_handle(_SEND_BTN_JS)
        if not await self._safe_click(send_handle, "botão Enviar"):
            try:
                await self.page.keyboard.press("Control+Enter")
            except Exception:
                return False
        await self.page.wait_for_timeout(1500)
        logger.info("DM enviado")
        return True
