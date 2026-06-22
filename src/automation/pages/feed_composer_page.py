"""Page object for composing/publishing an authored LinkedIn post.

Separate from ``feed_page.py`` (which reads the feed for like/comment/share).
O composer do LinkedIn 2026 renderiza o editor em **shadow DOM** (e há vários
``role='dialog'`` no feed, ex: overlay de mensagens), então `querySelector` cru
não acha o editor/botão. Usamos **locators de acessibilidade** do Playwright
(`get_by_role`), que enxergam o accessibility tree. Fluxo:

    feed → "Começar publicação" → editor (textbox) → type → "Publicar" → URL
"""

import random
import re

from playwright.async_api import Page

from src.config.settings import logger

FEED_URL = "https://www.linkedin.com/feed/"

# Nomes acessíveis (PT-BR + EN), estáveis entre versões da UI.
_START_RE = re.compile(r"come[çc]ar publica|start a post|criar publica", re.I)
_EDITOR_RE = re.compile(r"editor de texto|text editor", re.I)
_PUBLISH_RE = re.compile(r"^(publicar|post)$", re.I)


def _alert(step: str) -> None:
    """Loga erro, registra evento e avisa no Telegram que um passo falhou."""
    msg = f"publicação falhou no passo '{step}' — seletor pode ter mudado"
    logger.error(f"Autopost: {msg}")
    try:
        from src.core.use_cases.events_tracker import record_event

        record_event("autopost", "publish_fail", ok=False, detail=step)
    except Exception:
        pass
    try:
        from src.utils.telegram import send_telegram

        send_telegram(f"⚠️ <b>Autopost</b>: {msg}", topic="autopost")
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

    async def _capture_post_url(self) -> str:
        """Best-effort: após publicar, um toast oferece 'Ver publicação'."""
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
        """Abre o composer, digita ``text``, publica. Returns ``(ok, url)``."""
        await self.goto()

        # 1) abrir composer
        try:
            await self.page.get_by_role("button", name=_START_RE).first.click(
                timeout=8000
            )
        except Exception as e:
            logger.warning(f"start-post click failed: {e}")
            _alert("abrir composer")
            return False, ""
        await self.page.wait_for_timeout(1500)

        # 2) editor (textbox com nome "Editor de texto"; fallback: 1º textbox)
        editor = self.page.get_by_role("textbox", name=_EDITOR_RE)
        try:
            if not await editor.count():
                editor = self.page.get_by_role("textbox")
            await editor.first.click(timeout=8000)
            await editor.first.type(text, delay=random.randint(8, 25))
        except Exception as e:
            logger.warning(f"editor type failed: {e}")
            _alert("encontrar editor")
            return False, ""
        await self.page.wait_for_timeout(1000)

        # 3) publicar — espera o botão habilitar (texto digitado habilita)
        btn = self.page.get_by_role("button", name=_PUBLISH_RE).first
        try:
            await btn.wait_for(state="visible", timeout=8000)
            for _ in range(20):
                if not await btn.is_disabled():
                    break
                await self.page.wait_for_timeout(300)
            await btn.click(timeout=8000)
        except Exception as e:
            logger.warning(f"publish click failed: {e}")
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
