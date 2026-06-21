"""Page object for composing/publishing an authored LinkedIn post.

Separate from ``feed_page.py`` (which reads the feed for like/comment/share).
LinkedIn 2026 DOM is obfuscated, so selectors lean on stable aria-labels and
visible text, with JS fallbacks. Publish flow:

    feed → "Começar publicação" → editor → type → "Publicar" → capture URL
"""

import random

from playwright.async_api import Page

from src.config.settings import logger

FEED_URL = "https://www.linkedin.com/feed/"

# Estratégias em camadas: estrutural (mais estável) → aria-label/texto (fallback).
_START_POST_JS = """
() => {
    const isVisible = (b) => {
        const r = b.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    };
    // 1) seletor estrutural do card de compose no topo do feed
    const structural = document.querySelector(
        ".share-box-feed-entry__trigger, button.share-box-feed-entry__trigger, "
        + ".artdeco-card .share-box-feed-entry__top-bar button"
    );
    if (structural && isVisible(structural)) return structural;
    // 2) fallback por aria-label / texto visível
    const nodes = document.querySelectorAll("button, div[role='button']");
    for (const n of nodes) {
        if (!isVisible(n)) continue;
        const al = (n.getAttribute('aria-label') || '').toLowerCase();
        const txt = (n.innerText || '').trim().toLowerCase();
        if (/começar publica|comecar publica|start a post|criar publica/.test(al + ' ' + txt)) {
            return n;
        }
    }
    return null;
}
"""

_POST_BTN_JS = """
() => {
    const isVisible = (b) => {
        const r = b.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    };
    // 1) seletor estrutural do botão publicar dentro do modal de compose
    const scope = document.querySelector(
        ".share-creation-state, div[class*='share-box'], div[role='dialog']"
    ) || document;
    const structural = scope.querySelector(".share-actions__primary-action");
    if (structural && !structural.disabled && isVisible(structural)) return structural;
    // 2) fallback por aria-label / texto visível
    const btns = scope.querySelectorAll('button');
    for (const b of btns) {
        if (b.disabled || !isVisible(b)) continue;
        const al = (b.getAttribute('aria-label') || '').toLowerCase();
        const txt = (b.innerText || '').trim().toLowerCase();
        if (al === 'publicar' || al === 'post' || txt === 'publicar' || txt === 'post') {
            return b;
        }
    }
    return null;
}
"""


def _alert(step: str) -> None:
    """Loga erro e avisa no Telegram que um passo da publicação falhou."""
    msg = f"publicação falhou no passo '{step}' — seletor pode ter mudado"
    logger.error(f"Autopost: {msg}")
    try:
        from src.utils.telegram import send_telegram

        send_telegram(f"⚠️ <b>Autopost</b>: {msg}")
    except Exception:
        pass


class FeedComposerPage:
    def __init__(self, page: Page, url: str = FEED_URL):
        self.page = page
        self.url = url

    async def goto(self) -> None:
        logger.info(f"Opening feed for compose: {self.url}")
        await self.page.goto(self.url, wait_until="domcontentloaded")
        await self.page.wait_for_timeout(2500)

    async def _safe_click_handle(self, handle, what: str) -> bool:
        elem = handle.as_element()
        if not elem:
            logger.warning(f"{what} not found")
            return False
        try:
            await elem.click(timeout=5000)
            return True
        except Exception:
            try:
                await elem.evaluate("el => el.click()")
                return True
            except Exception as e:
                logger.warning(f"click on {what} failed: {e}")
                return False

    async def _find_editor(self):
        for _ in range(12):
            editors = await self.page.query_selector_all(
                "[contenteditable='true'][role='textbox']"
            )
            for ed in editors:
                try:
                    if await ed.is_visible():
                        return ed
                except Exception:
                    continue
            await self.page.wait_for_timeout(300)
        return None

    async def _capture_post_url(self) -> str:
        """Best-effort: after publish a toast offers 'Ver publicação'."""
        try:
            handle = await self.page.evaluate_handle("""
() => {
    const links = document.querySelectorAll('a[href*="/feed/update/"]');
    for (const a of links) {
        const r = a.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) return a.href;
    }
    return '';
}
""")
            return await handle.json_value() or ""
        except Exception:
            return ""

    async def publish(self, text: str) -> tuple[bool, str]:
        """Open composer, type ``text``, publish. Returns ``(ok, url)``."""
        await self.goto()

        start_handle = await self.page.evaluate_handle(_START_POST_JS)
        if not await self._safe_click_handle(start_handle, "start-post button"):
            _alert("abrir composer")
            return False, ""
        await self.page.wait_for_timeout(2000)

        editor = await self._find_editor()
        if not editor:
            _alert("encontrar editor")
            return False, ""
        try:
            await editor.click()
            await self.page.wait_for_timeout(300)
            await editor.type(text, delay=random.randint(8, 25))
            await self.page.wait_for_timeout(1000)
        except Exception as e:
            logger.warning(f"Typing post failed: {e}")
            return False, ""

        post_handle = await self.page.evaluate_handle(_POST_BTN_JS)
        if not await self._safe_click_handle(post_handle, "publish button"):
            _alert("clicar publicar")
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                pass
            return False, ""

        await self.page.wait_for_timeout(3000)
        url = await self._capture_post_url()
        if not url:
            logger.warning("Post publicado mas URL não capturada (toast ausente?)")
        logger.info(f"Post publicado (url={url or 'desconhecida'})")
        return True, url
