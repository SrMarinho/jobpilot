import asyncio
import hashlib
import random
import re
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

_POST_URN_JS = """
(el) => {
    const RE = /urn:li:(activity|share|ugcPost):\\d+/;
    const scan = (node) => {
        if (!node || !node.getAttribute) return null;
        for (const a of ['data-urn', 'data-id', 'data-activity-urn']) {
            const v = node.getAttribute(a);
            if (v) { const m = v.match(RE); if (m) return m[0]; }
        }
        return null;
    };
    let cur = el;
    for (let i = 0; i < 20 && cur; i++) {
        const u = scan(cur);
        if (u) return u;
        cur = cur.parentElement;
    }
    for (const n of el.querySelectorAll('[data-urn],[data-id],[data-activity-urn]')) {
        const u = scan(n);
        if (u) return u;
    }
    return null;
}
"""

_LIKE_BTN_JS = """
(el) => {
    const isVisible = (b) => {
        const r = b.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    };
    const btns = el.querySelectorAll('button');
    // Primary: aria-label contains "reação" / "react" (LinkedIn 2026 pattern)
    for (const b of btns) {
        const al = (b.getAttribute('aria-label') || '').toLowerCase();
        if (/reação|reacao|react|curti|like/.test(al) && isVisible(b)) return b;
    }
    // Fallback: aria-pressed toggle excluding action bar peers
    const excluded = /coment|compart|salvar|save|send|enviar|mais|repost|seguir|follow|conectar|connect|ocultar|publicação|publicacao|abrir menu/i;
    for (const b of btns) {
        const al = b.getAttribute('aria-label') || '';
        if (excluded.test(al)) continue;
        if (b.hasAttribute('aria-pressed') && isVisible(b)) return b;
    }
    return null;
}
"""


class FeedPage:
    def __init__(self, page: Page, url: str = FEED_URL):
        self.page = page
        self.url = url

    async def goto(self) -> None:
        from src.automation.checkpoint import ensure_not_blocked

        logger.info(f"Opening feed: {self.url}")
        await self.page.goto(self.url, wait_until="domcontentloaded")
        await ensure_not_blocked(self.page, "engage")
        try:
            await self.page.wait_for_selector(_COMMENT_SELECTOR, timeout=20000)
        except Exception:
            logger.warning("No comment buttons found on feed within timeout")
        await self.page.wait_for_timeout(2000)

    async def scroll_feed(self, n: int = 5, pause_ms: int = 1500) -> None:
        for i in range(n):
            # Scroll to bottom to force LinkedIn lazy-load of more posts
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await self.page.wait_for_timeout(pause_ms)
            # Nudge up then down — triggers IntersectionObserver loaders
            await self.page.evaluate("window.scrollBy(0, -300)")
            await self.page.wait_for_timeout(300)
            await self.page.evaluate("window.scrollBy(0, 600)")
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
        # URN estável do LinkedIn (urn:li:activity/share/ugcPost) — não muda ao
        # engajar, ao contrário do contador de reações/comentários no innerText.
        try:
            stable = await post.evaluate(_POST_URN_JS)
        except Exception:
            stable = None
        if stable:
            return stable
        # Fallback: hash de conteúdo (compat com registros antigos)
        try:
            text = await post.evaluate("el => (el.innerText || '').slice(0, 500)")
        except Exception:
            return None
        if not text:
            return None
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
        return f"feed:{digest}"

    @staticmethod
    def _is_skip_line(line: str) -> bool:
        if not line or len(line) < 3:
            return True
        low = line.lower()
        skip_exact = {
            "publicação no feed",
            "publicacao no feed",
            "sugestões",
            "sugestoes",
            "suggested",
            "recentes",
            "recent",
            "promovido",
            "promoted",
            "seguir",
            "follow",
            "follow back",
            "conectar",
            "connect",
            "curtir",
            "like",
            "comentar",
            "comment",
            "compartilhar",
            "share",
            "salvar",
            "save",
            "enviar",
            "send",
            "mais",
            "more",
            "ver tradução",
            "see translation",
            "ver mais",
            "see more",
            "carregar mais",
            "load more",
            "mensagem",
            "message",
        }
        if low in skip_exact:
            return True
        if line.strip(" •·∙") == "":
            return True
        # Connection degree / timestamp lines
        if "•" in line and len(line) < 25:
            return True
        # Pure number (counter)
        compact = line.replace(".", "").replace(",", "").replace(" ", "")
        if compact.isdigit():
            return True
        # Passive engagement headers: "X gostou disso", "X liked", "X comentou", "X compartilhou"
        suffixes = (
            " gostou",
            " gostou disso",
            " curtiu",
            " curtiu isso",
            " comentou",
            " comentou isso",
            " compartilhou",
            " compartilhou isso",
            " liked",
            " liked this",
            " commented",
            " commented on this",
            " shared",
            " shared this",
            " reposted",
            " reposted this",
            " seguiu",
            " segue",
            " follows",
            " followed",
        )
        for sfx in suffixes:
            if low.endswith(sfx):
                return True
        return False

    async def _post_lines(self, post: ElementHandle) -> list[str]:
        try:
            raw = await post.evaluate("el => el.innerText || ''")
        except Exception:
            return []
        return [line.strip() for line in raw.split("\n")]

    async def get_post_author(self, post: ElementHandle) -> str:
        for line in await self._post_lines(post):
            if self._is_skip_line(line):
                continue
            # Author rarely has pipes/bullets (those = headline)
            if "|" in line or "•" in line:
                continue
            return line
        return "unknown"

    async def get_post_author_headline(self, post: ElementHandle) -> str:
        # Headline = linha logo após o autor (ex: "Software Engineer | Python").
        # Pula timestamps ("2 h", "1 sem", "Editado") e o grau de conexão.
        nonskip = [
            line
            for line in await self._post_lines(post)
            if not self._is_skip_line(line)
        ]
        for line in nonskip[1:4]:  # autor = [0]; headline vem logo depois
            low = line.lower()
            # timestamp/idade do post: "2 h", "3 d", "1 sem", "5 min", "agora"
            if re.match(r"^\d+\s*(h|d|sem|min|mês|meses|mo|w|m|a)\b", low):
                continue
            if low in ("editado", "edited", "agora", "now"):
                continue
            if "|" in line or "•" in line or len(line) > 12:
                return line
        return ""

    async def get_post_text(self, post: ElementHandle) -> str:
        lines = await self._post_lines(post)
        # Trim trailing counter/short noise
        while lines and (not lines[-1] or lines[-1].isdigit() or len(lines[-1]) < 3):
            lines.pop()
        # Skip header lines: label, section, author, headline, timestamp, follow button
        body_lines: list[str] = []
        seen_body = False
        for line in lines:
            if not seen_body:
                if self._is_skip_line(line):
                    continue
                # Headlines tend to have | or be very long noun-phrase
                if "|" in line and len(line) > 40:
                    continue
                # Author detected → next non-skip is body
                seen_body = True
                continue
            if self._is_skip_line(line):
                continue
            body_lines.append(line)
        return "\n".join(body_lines).strip()

    async def _scroll_into_view(self, post: ElementHandle) -> None:
        try:
            await post.scroll_into_view_if_needed(timeout=3000)
            await self.page.wait_for_timeout(400)
        except Exception:
            pass

    async def dismiss_overlays(self) -> None:
        """Close lingering menus/toasts/modals that intercept pointer events."""
        for _ in range(3):
            try:
                await self.page.keyboard.press("Escape")
                await self.page.wait_for_timeout(250)
            except Exception:
                break
        # Click neutral area top-left to dismiss popovers
        try:
            await self.page.mouse.click(5, 200)
            await self.page.wait_for_timeout(300)
        except Exception:
            pass

    async def _safe_click(self, elem: ElementHandle, what: str = "element") -> bool:
        """Click with fast timeout; fall back to JS click on pointer interception."""
        try:
            await elem.click(timeout=5000)
            return True
        except Exception as e:
            logger.debug(f"Normal click on {what} failed ({e}); trying JS click")
        try:
            await elem.evaluate("el => el.click()")
            return True
        except Exception as e:
            logger.warning(f"JS click on {what} also failed: {e}")
            return False

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
            label = (await elem.get_attribute("aria-label") or "").lower()
        except Exception:
            label = ""
        # Already liked patterns. "nenhuma reação" means NOT liked yet → safe to click.
        already_liked_markers = (
            "curtido",
            "curti ",
            "liked",
            "gostei",
            "aplaudido",
            "comemorado",
            "amado",
            "achei interessante",
            "achei engra",
        )
        if any(m in label for m in already_liked_markers) and "nenhuma" not in label:
            logger.info(f"Already liked (label={label!r}), skipping")
            return False
        if await self._safe_click(elem, "like button"):
            logger.info(f"Liked post (button label={label!r})")
            await self.page.wait_for_timeout(800)
            return True
        logger.warning("Like click failed")
        return False

    async def _find_visible_editor(self) -> Optional[ElementHandle]:
        # LinkedIn 2026: editor div[role=textbox][contenteditable=true]
        # aria-label contains "comentário" / "comment".
        for _ in range(10):
            editors = await self.page.query_selector_all(
                "[contenteditable='true'][role='textbox']"
            )
            for ed in reversed(editors):
                try:
                    al = (await ed.get_attribute("aria-label") or "").lower()
                    if "coment" not in al and "comment" not in al:
                        continue
                    if await ed.is_visible():
                        try:
                            await ed.scroll_into_view_if_needed(timeout=2000)
                        except Exception:
                            pass
                        return ed
                except Exception:
                    continue
            await self.page.wait_for_timeout(300)
        # Last-resort: any visible contenteditable
        editors = await self.page.query_selector_all("[contenteditable='true']")
        for ed in reversed(editors):
            try:
                if await ed.is_visible():
                    return ed
            except Exception:
                continue
        return None

    async def _click_submit_comment(self) -> bool:
        # Submit only enables after typing. Search via aria/text after a short delay.
        await self.page.wait_for_timeout(500)
        btn_handle = await self.page.evaluate_handle("""
() => {
    const isVisible = (b) => {
        const r = b.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    };
    const btns = document.querySelectorAll('button');
    for (const b of btns) {
        if (b.disabled) continue;
        if (!isVisible(b)) continue;
        const al = (b.getAttribute('aria-label') || '').toLowerCase();
        const txt = (b.innerText || '').trim().toLowerCase();
        if (/publicar comentário|publicar comentario|post comment|enviar comentário|enviar comentario/.test(al)) return b;
        if (txt === 'comentar' && al !== 'comentar') return b;
        if (txt === 'publicar' || txt === 'post' || txt === 'comment') return b;
    }
    // Generic fallback: enabled button with text "Comentar"/"Publicar" inside comment box
    for (const b of btns) {
        if (b.disabled || !isVisible(b)) continue;
        const al = (b.getAttribute('aria-label') || '').toLowerCase();
        if (al === 'comentar') {
            // Only accept if NOT the open-comments-section button (has aria-label exact "Comentar" + count text)
            const txt = (b.innerText || '').trim();
            if (!/^\\d+$/.test(txt)) return b;
        }
    }
    return null;
}
        """)
        elem = btn_handle.as_element()
        if elem:
            try:
                label = await elem.get_attribute("aria-label") or ""
                await elem.click()
                logger.info(f"Clicked submit comment (aria={label!r})")
                return True
            except Exception as e:
                logger.debug(f"Submit click failed: {e}")
        # Fallback: keyboard shortcut Ctrl+Enter
        try:
            await self.page.keyboard.press("Control+Enter")
            logger.info("Submitted comment via Ctrl+Enter fallback")
            return True
        except Exception:
            return False

    async def submit_comment(self, post: ElementHandle, text: str) -> bool:
        await self.dismiss_overlays()
        await self._scroll_into_view(post)
        comment_btn = await post.query_selector(_COMMENT_SELECTOR)
        if not comment_btn:
            logger.warning("Comment button not found in container")
            return False
        if not await self._safe_click(comment_btn, "comment button"):
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
        await self.dismiss_overlays()
        await self._scroll_into_view(post)
        share_btn = await post.query_selector(_SHARE_SELECTOR)
        if not share_btn:
            logger.warning("Share button not found in container")
            return False
        if not await self._safe_click(share_btn, "share button"):
            return False
        await self.page.wait_for_timeout(1500)

        # LinkedIn 2026: share menu has 2 div[role=button] items.
        # Item 1 = "Compartilhe com suas ideias" (quote-share, opens composer)
        # Item 2 = "Compartilhar / Compartilhe a publicação ..." (direct repost)
        # We want the direct repost: match by "Compartilhe a publicação" text.
        repost_handle = await self.page.evaluate_handle("""
() => {
    const items = document.querySelectorAll("div[role='button'], div[role='menuitem'], button");
    for (const el of items) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const txt = (el.innerText || '').toLowerCase();
        if (/compartilhe a publica|share .* post|repostar agora|repost now|repost$/.test(txt)) {
            return el;
        }
    }
    return null;
}
        """)
        repost_elem = repost_handle.as_element()
        if not repost_elem:
            # Fallback: legacy labels
            for label in ("Repostar agora", "Repost agora", "Repost now"):
                try:
                    opt = await self.page.query_selector(
                        f"button:has-text('{label}'), div[role='button']:has-text('{label}')"
                    )
                    if opt and await opt.is_visible():
                        repost_elem = opt
                        break
                except Exception:
                    continue
        if not repost_elem:
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                pass
            logger.warning("Repost option not found in share menu")
            return False
        if await self._safe_click(repost_elem, "repost option"):
            logger.info("Reposted (compartilhar direto)")
            await self.page.wait_for_timeout(2000)
            return True
        logger.warning("Repost click failed")
        return False

    async def random_pause(self, lo: int = 5, hi: int = 15) -> None:
        await asyncio.sleep(random.randint(lo, hi))
