import asyncio
import random
from typing import Optional

from playwright.async_api import Page, ElementHandle

from src.config.settings import logger


FEED_URL = "https://www.linkedin.com/feed/"


class FeedPage:
    def __init__(self, page: Page, url: str = FEED_URL):
        self.page = page
        self.url = url

    async def goto(self) -> None:
        logger.info(f"Opening feed: {self.url}")
        await self.page.goto(self.url, wait_until="domcontentloaded")
        try:
            await self.page.wait_for_selector(
                "div[data-urn], div.feed-shared-update-v2", timeout=15000
            )
        except Exception:
            logger.warning("Feed posts did not load in time")

    async def scroll_feed(self, n: int = 5, pause_ms: int = 1500) -> None:
        for i in range(n):
            await self.page.evaluate("window.scrollBy(0, window.innerHeight * 1.2)")
            await self.page.wait_for_timeout(pause_ms)
            logger.debug(f"Scrolled feed {i + 1}/{n}")

    async def get_posts(self) -> list[ElementHandle]:
        posts = await self.page.query_selector_all(
            "div.feed-shared-update-v2[data-urn], div[data-urn^='urn:li:activity']"
        )
        logger.info(f"Found {len(posts)} posts on feed")
        return posts

    async def get_post_urn(self, post: ElementHandle) -> Optional[str]:
        try:
            urn = await post.get_attribute("data-urn")
            if urn:
                return urn
        except Exception:
            pass
        return None

    async def get_post_author(self, post: ElementHandle) -> str:
        for sel in [
            ".update-components-actor__title span[aria-hidden='true']",
            ".update-components-actor__title",
            ".update-components-actor__name",
            "span.feed-shared-actor__name",
        ]:
            try:
                el = await post.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if text:
                        return text.split("\n")[0]
            except Exception:
                continue
        return "unknown"

    async def get_post_text(self, post: ElementHandle) -> str:
        for sel in [
            ".update-components-text",
            ".feed-shared-text",
            ".update-components-update-v2__commentary",
        ]:
            try:
                el = await post.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if text:
                        return text
            except Exception:
                continue
        return ""

    async def _scroll_into_view(self, post: ElementHandle) -> None:
        try:
            await post.scroll_into_view_if_needed(timeout=3000)
            await self.page.wait_for_timeout(400)
        except Exception:
            pass

    async def like_post(self, post: ElementHandle) -> bool:
        await self._scroll_into_view(post)
        for sel in [
            "button[aria-label*='Reagir como'][aria-pressed='false']",
            "button[aria-label*='Reagir'][aria-pressed='false']",
            "button[aria-label*='React Like'][aria-pressed='false']",
            "button[aria-label*='Like'][aria-pressed='false']",
            "button.react-button__trigger[aria-pressed='false']",
        ]:
            try:
                btn = await post.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    logger.info("Liked post")
                    await self.page.wait_for_timeout(800)
                    return True
            except Exception:
                continue
        logger.warning("Like button not found or already pressed")
        return False

    async def submit_comment(self, post: ElementHandle, text: str) -> bool:
        await self._scroll_into_view(post)

        comment_btn = None
        for sel in [
            "button[aria-label*='Comentar']",
            "button[aria-label*='Comment']",
        ]:
            try:
                comment_btn = await post.query_selector(sel)
                if comment_btn and await comment_btn.is_visible():
                    break
            except Exception:
                continue
        if not comment_btn:
            logger.warning("Comment button not found")
            return False

        try:
            await comment_btn.click()
        except Exception as e:
            logger.warning(f"Comment button click failed: {e}")
            return False
        await self.page.wait_for_timeout(1200)

        editor = None
        for sel in [
            ".comments-comment-box__form [contenteditable='true']",
            ".comments-comment-box [role='textbox']",
            "[contenteditable='true'][role='textbox']",
        ]:
            try:
                ed = await post.query_selector(sel)
                if ed and await ed.is_visible():
                    editor = ed
                    break
            except Exception:
                continue
        if not editor:
            try:
                editor = await self.page.query_selector(
                    "[contenteditable='true'][role='textbox']"
                )
            except Exception:
                editor = None
        if not editor:
            logger.warning("Comment editor not found")
            return False

        try:
            await editor.click()
            await self.page.wait_for_timeout(300)
            await editor.type(text, delay=random.randint(20, 60))
            await self.page.wait_for_timeout(600)
        except Exception as e:
            logger.warning(f"Typing comment failed: {e}")
            return False

        for sel in [
            "button.comments-comment-box__submit-button",
            "button[aria-label*='Publicar comentário']",
            "button[aria-label*='Post comment']",
            "button:has-text('Publicar')",
            "button:has-text('Post')",
        ]:
            try:
                submit = await post.query_selector(sel)
                if not submit:
                    submit = await self.page.query_selector(sel)
                if submit and await submit.is_visible() and await submit.is_enabled():
                    await submit.click()
                    logger.info(f"Submitted comment: {text!r}")
                    await self.page.wait_for_timeout(2000)
                    return True
            except Exception:
                continue
        logger.warning("Comment submit button not found")
        return False

    async def share_post(self, post: ElementHandle) -> bool:
        await self._scroll_into_view(post)
        share_btn = None
        for sel in [
            "button[aria-label*='Compartilhar']",
            "button[aria-label*='Share']",
            "button.social-share-button",
        ]:
            try:
                share_btn = await post.query_selector(sel)
                if share_btn and await share_btn.is_visible():
                    break
            except Exception:
                continue
        if not share_btn:
            logger.warning("Share button not found")
            return False
        try:
            await share_btn.click()
        except Exception as e:
            logger.warning(f"Share button click failed: {e}")
            return False
        await self.page.wait_for_timeout(1200)

        for sel in [
            "div[role='menuitem']:has-text('Repostar agora')",
            "div[role='button']:has-text('Repostar agora')",
            "button:has-text('Repostar agora')",
            "div[role='menuitem']:has-text('Repost')",
            "button:has-text('Repost now')",
            "button[aria-label*='Repostar']",
        ]:
            try:
                opt = await self.page.query_selector(sel)
                if opt and await opt.is_visible():
                    await opt.click()
                    logger.info("Shared (reposted) post")
                    await self.page.wait_for_timeout(1500)
                    return True
            except Exception:
                continue
        try:
            await self.page.keyboard.press("Escape")
        except Exception:
            pass
        logger.warning("Repost option not found in share menu")
        return False

    async def random_pause(self, lo: int = 5, hi: int = 15) -> None:
        await asyncio.sleep(random.randint(lo, hi))
