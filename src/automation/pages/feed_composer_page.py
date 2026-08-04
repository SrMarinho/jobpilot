"""Page object for composing/publishing an authored LinkedIn post.

Separate from ``feed_page.py`` (which reads the feed for like/comment/share).
O composer do LinkedIn 2026 renderiza o editor em **shadow DOM** (e há vários
``role='dialog'`` no feed, ex: overlay de mensagens), então `querySelector` cru
não acha o editor/botão. Usamos **locators de acessibilidade** do Playwright
(`get_by_role`), que enxergam o accessibility tree. Fluxo:

    feed → "Começar publicação" → editor (textbox) → type → "Publicar" → URL
"""

import re

from playwright.async_api import Page

from src.config.settings import logger
from src.utils.pacing import type_like_human

FEED_URL = "https://www.linkedin.com/feed/"

# Nomes acessíveis (PT-BR + EN), estáveis entre versões da UI.
_START_RE = re.compile(r"come[çc]ar publica|start a post|criar publica", re.I)
_EDITOR_RE = re.compile(r"editor de texto|text editor", re.I)
_PUBLISH_RE = re.compile(r"^(publicar|post)$", re.I)
_MEDIA_RE = re.compile(
    r"adicionar (m[íi]dia|foto|imagem)|add (media|a photo|photo)|m[íi]dia", re.I
)
_DONE_RE = re.compile(r"^(concluído|concluir|avançar|next|done|pronto)$", re.I)


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

    async def _attach_image(self, image_path: str) -> bool:
        """Anexa uma imagem ao composer. Best-effort; não levanta exceção.

        Clica o botão de mídia, seta o arquivo no input[type=file] (mesmo oculto)
        e confirma o diálogo. Selectors LinkedIn 2026 best-effort: qualquer falha
        loga alerta e devolve False (o publish segue só com texto).
        """
        from pathlib import Path

        if not Path(image_path).exists():
            logger.warning(f"Imagem não encontrada, publicando sem ela: {image_path}")
            return False
        try:
            btn = self.page.get_by_role("button", name=_MEDIA_RE).first
            if await btn.count():
                await btn.click(timeout=6000)
                await self.page.wait_for_timeout(1200)

            file_input = self.page.locator('input[type="file"]').first
            await file_input.set_input_files(image_path, timeout=8000)
            await self.page.wait_for_timeout(2500)  # upload/preview

            # confirma o diálogo de mídia se houver (Concluído/Avançar/Next)
            done = self.page.get_by_role("button", name=_DONE_RE).first
            if await done.count() and not await done.is_disabled():
                await done.click(timeout=6000)
                await self.page.wait_for_timeout(1200)
            logger.info("Imagem anexada ao post")
            return True
        except Exception as e:
            logger.warning(f"Falha ao anexar imagem (segue só texto): {e}")
            _alert("anexar imagem")
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    async def _open_composer(self) -> bool:
        """Clica em 'Começar publicação'. LinkedIn 2026: é um <a>/<div>, não
        ``role=button`` — então tenta várias estratégias em ordem.
        """
        candidates = [
            self.page.get_by_role("button", name=_START_RE),
            self.page.locator("a, div[role=button], button").filter(has_text=_START_RE),
            self.page.locator("[aria-label]").filter(has_text=_START_RE),
            self.page.get_by_text(_START_RE),
        ]
        for loc in candidates:
            try:
                if await loc.count():
                    await loc.first.click(timeout=6000)
                    return True
            except Exception as e:
                logger.warning(f"open-composer candidate falhou: {e}")
                continue
        return False

    async def publish(
        self, text: str, image_path: str | None = None
    ) -> tuple[bool, str]:
        """Abre o composer, digita ``text``, anexa imagem opcional, publica.

        Returns ``(ok, url)``. Falha ao anexar imagem NÃO aborta: publica só texto.
        """
        await self.goto()

        # 1) abrir composer
        if not await self._open_composer():
            logger.warning("start-post click failed: nenhum seletor encontrou o botão")
            _alert("abrir composer")
            return False, ""
        await self.page.wait_for_timeout(1500)

        # 2) editor (textbox com nome "Editor de texto"; fallback: 1º textbox)
        editor = self.page.get_by_role("textbox", name=_EDITOR_RE)
        try:
            if not await editor.count():
                editor = self.page.get_by_role("textbox")
            await editor.first.click(timeout=8000)
            await type_like_human(editor.first, text)
        except Exception as e:
            logger.warning(f"editor type failed: {e}")
            _alert("encontrar editor")
            return False, ""
        await self.page.wait_for_timeout(1000)

        # 2.5) anexar imagem (best-effort — se falhar, segue só com texto)
        if image_path:
            await self._attach_image(image_path)

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
