import asyncio
import hashlib
import random
from typing import Optional

from playwright.async_api import Page, ElementHandle

from src.config.settings import logger


FEED_URL = "https://www.linkedin.com/feed/"

_COMMENT_SELECTOR = "button[aria-label='Comentar'], button[aria-label='Comment']"
_SHARE_SELECTOR = "button[aria-label='Compartilhar'], button[aria-label='Share']"

_WALK_UP_JS = """
(el, shareSelector) => {
    let cur = el;
    for (let i = 0; i < 15; i++) {
        cur = cur.parentElement;
        if (!cur) return null;
        const hasShare = cur.querySelector(shareSelector);
        const txtLen = (cur.innerText || '').length;
        if (hasShare && txtLen > 200) return cur;
    }
    return null;
}
"""

_LIKE_BTN_JS = """
(el) => {
    const excluded = /coment|compart|salvar|save|send|enviar|mais|repost|seguir|follow|conectar|connect/i;
    const btns = el.querySelectorAll('button');
    for (const b of btns) {
        const al = b.getAttribute('aria-label') || '';
        if (excluded.test(al)) continue;
        if (!b.hasAttribute('aria-pressed')) continue;
        const rect = b.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) continue;
        return b;
    }
    for (const b of btns) {
        const al = ((b.getAttribute('aria-label') || '') + ' ' + (b.innerText || '')).toLowerCase();
        if (/curtir|^like$|reagir/.test(al)) {
            const rect = b.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;
            return b;
        }
    }
    return null;
}
"""


class FeedPage:
    def __init__(self, page: Page, url: str = FEED_URL):
        self.page = page
        self.url = url

    async def goto(self) -> None:
        logger.info(f"Opening feed: {self.url}")
        await self.page.goto(self.url, wait_until="domcontentloaded")
        try:
            await self.page.wait_for_selector(_COMMENT_SELECTOR, timeout=20000)
        except Exception:
            logger.warning("No comment buttons found on feed within timeout")
        await self.page.wait_for_timeout(2000)

    async def scroll_feed(self, n: int = 5, pause_ms: int = 1500) -> None:
        for i in range(n):
            await self.page.evaluate("window.scrollBy(0, window.innerHeight * 1.2)")
            await self.page.wait_for_timeout(pause_ms)
            logger.debug(f"Scrolled feed {i + 1}/{n}")

    async def get_posts(self) -> list[ElementHandle]:
        comment_btns = await self.page.query_selector_all(_COMMENT_SELECTOR)
        posts: list[ElementHandle] = []
        seen_keys: set[str] = set()
        for btn in comment_btns:
            try:
                container_handle = await btn.evaluate_handle(
                    _WALK_UP_JS, _SHARE_SELECTOR
                )
            except Exception as e:
                logger.debug(f"Walk-up failed: {e}")
                continue
            elem = container_handle.as_element()
            if not elem:
                continue
            try:
                key = await elem.evaluate("el => (el.innerText || '').slice(0, 80)")
            except Exception:
                continue
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            posts.append(elem)
        logger.info(f"Found {len(posts)} posts via walk-up")
        return posts

    async def get_post_urn(self, post: ElementHandle) -> Optional[str]:
        try:
            text = await post.evaluate("el => (el.innerText || '').slice(0, 500)")
        except Exception:
            return None
        if not text:
            return None
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        return f"feed:{digest}"

    async def get_post_author(self, post: ElementHandle) -> str:
        try:
            raw = await post.evaluate("el => el.innerText || ''")
        except Exception:
            return "unknown"
        for line in raw.split("\n"):
            line = line.strip()
            if len(line) >= 3 and not line.isdigit():
                return line.split("•")[0].strip()
        return "unknown"

    async def get_post_text(self, post: ElementHandle) -> str:
        try:
            raw = await post.evaluate("el => el.innerText || ''")
        except Exception:
            return ""
        lines = [line.strip() for line in raw.split("\n")]
        while lines and (not lines[-1] or lines[-1].isdigit() or len(lines[-1]) < 3):
            lines.pop()
        body = "\n".join(lines[2:]) if len(lines) > 2 else "\n".join(lines)
        return body.strip()

    async def _scroll_into_view(self, post: ElementHandle) -> None:
        try:
            await post.scroll_into_view_if_needed(timeout=3000)
            await self.page.wait_for_timeout(400)
        except Exception:
            pass

    async def like_post(self, post: ElementHandle) -> bool:
        await self._scroll_into_view(post)
        try:
            btn_handle = await post.evaluate_handle(_LIKE_BTN_JS)
        except Exception as e:
            logger.warning(f"Like discovery failed: {e}")
            return False
        elem = btn_handle.as_element()
        if not elem:
            logger.warning("Like button not found in post container")
            return False
        try:
            pressed = await elem.get_attribute("aria-pressed")
        except Exception:
            pressed = None
        if pressed == "true":
            logger.info("Already liked, skipping")
            return False
        try:
            await elem.click()
            logger.info("Liked post")
            await self.page.wait_for_timeout(800)
            return True
        except Exception as e:
            logger.warning(f"Like click failed: {e}")
            return False

    async def _find_visible_editor(self) -> Optional[ElementHandle]:
        editors = await self.page.query_selector_all(
            "[contenteditable='true'][role='textbox']"
        )
        for ed in reversed(editors):
            try:
                if await ed.is_visible():
                    return ed
            except Exception:
                continue
        return None

    async def _click_submit_comment(self) -> bool:
        labels = [
            "Publicar comentário",
            "Post comment",
            "Publicar",
            "Comentar comentário",
            "Comment",
        ]
        for label in labels:
            for sel in (
                f"button[aria-label='{label}']",
                f"button:has-text('{label}')",
            ):
                try:
                    btn = await self.page.query_selector(sel)
                    if btn and await btn.is_visible() and await btn.is_enabled():
                        await btn.click()
                        logger.info(f"Clicked submit comment ({label!r})")
                        return True
                except Exception:
                    continue
        return False

    async def submit_comment(self, post: ElementHandle, text: str) -> bool:
        await self._scroll_into_view(post)
        comment_btn = await post.query_selector(_COMMENT_SELECTOR)
        if not comment_btn:
            logger.warning("Comment button not found in container")
            return False
        try:
            await comment_btn.click()
        except Exception as e:
            logger.warning(f"Comment button click failed: {e}")
            return False
        await self.page.wait_for_timeout(1500)

        editor = await self._find_visible_editor()
        if not editor:
            logger.warning("Comment editor not visible after opening box")
            return False
        try:
            await editor.click()
            await self.page.wait_for_timeout(300)
            await editor.type(text, delay=random.randint(20, 60))
            await self.page.wait_for_timeout(700)
        except Exception as e:
            logger.warning(f"Typing comment failed: {e}")
            return False

        if not await self._click_submit_comment():
            logger.warning("Could not find submit button for comment")
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                pass
            return False
        logger.info(f"Submitted comment: {text!r}")
        await self.page.wait_for_timeout(2000)
        return True

    async def share_post(self, post: ElementHandle) -> bool:
        await self._scroll_into_view(post)
        share_btn = await post.query_selector(_SHARE_SELECTOR)
        if not share_btn:
            logger.warning("Share button not found in container")
            return False
        try:
            await share_btn.click()
        except Exception as e:
            logger.warning(f"Share button click failed: {e}")
            return False
        await self.page.wait_for_timeout(1200)

        option_labels = [
            "Repostar agora",
            "Repost agora",
            "Repost",
            "Compartilhar como repostagem",
            "Repost now",
        ]
        for label in option_labels:
            for sel in (
                f"div[role='menuitem']:has-text('{label}')",
                f"div[role='button']:has-text('{label}')",
                f"button:has-text('{label}')",
                f"button[aria-label='{label}']",
            ):
                try:
                    opt = await self.page.query_selector(sel)
                    if opt and await opt.is_visible():
                        await opt.click()
                        logger.info(f"Reposted ({label!r})")
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
