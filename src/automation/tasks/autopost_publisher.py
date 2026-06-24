"""Publicação de um post autoral no LinkedIn (browser).

Isolado aqui para que tanto o bot persistente quanto o run agendado
(``autopost --publish-approved``) usem o mesmo caminho de publicação.
"""

from playwright.async_api import async_playwright

from src.interfaces.cli.browser import (
    create_context,
    acquire_browser_lock,
    _release_browser_lock,
)
from src.automation.pages.feed_composer_page import FeedComposerPage


async def publish_content(
    content: str, image_path: str | None = None
) -> tuple[bool, str]:
    """Abre o composer sob o browser lock e publica ``content`` (+ imagem opcional).

    Returns ``(ok, url)``.
    """
    lock = await acquire_browser_lock("autopost_publish")
    try:
        async with async_playwright() as pw:
            context, page = await create_context(pw, force_headless=False)
            try:
                return await FeedComposerPage(page).publish(content, image_path)
            finally:
                try:
                    await context.close()
                except Exception:
                    pass
    finally:
        _release_browser_lock(lock, "autopost_publish")
