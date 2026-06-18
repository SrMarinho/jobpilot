"""Inspect LinkedIn feed DOM — dump post + action button structure to file.

Output written to scripts/_linkedin_feed_dump.txt for inspection.
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from src.interfaces.cli.persistence import BOT_PROFILE_DIR

URL = "https://www.linkedin.com/feed/"
OUT = Path(__file__).resolve().parent / "_linkedin_feed_dump.txt"


async def main():
    stealth = Stealth()
    lines: list[str] = []

    def log(s: str) -> None:
        lines.append(s)
        print(s, flush=True)

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=BOT_PROFILE_DIR,
            headless=False,
            channel="chrome",
            args=["--start-maximized"],
            no_viewport=True,
        )
        await stealth.apply_stealth_async(context)
        page = context.pages[0] if context.pages else await context.new_page()

        log(f"Target URL: {URL}")
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(6000)

        log(f"Final URL: {page.url}")
        log(f"Title: {await page.title()}")

        for _ in range(6):
            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(800)
        await page.wait_for_timeout(1500)

        try:
            await page.screenshot(
                path=str(Path(__file__).parent / "_linkedin_feed_dump.png"),
                full_page=False,
            )
            log("Screenshot saved: scripts/_linkedin_feed_dump.png")
        except Exception as e:
            log(f"Screenshot failed: {e}")

        posts = await page.evaluate("""
            () => {
                const selectors = [
                    'div.feed-shared-update-v2[data-urn]',
                    "div[data-urn^='urn:li:activity']",
                    'div.feed-shared-update-v2',
                ];
                for (const sel of selectors) {
                    const els = document.querySelectorAll(sel);
                    if (els.length > 0) {
                        return {sel, count: els.length, sample: els[0].outerHTML.slice(0, 4000)};
                    }
                }
                return {sel: null, count: 0, sample: 'no post selector matched'};
            }
        """)
        log(
            f"\n--- POST CONTAINERS — selector: {posts['sel']!r}, count: {posts['count']} ---"
        )

        buttons = await page.evaluate("""
            () => {
                const out = [];
                document.querySelectorAll('button, a[role=button], div[role=button]').forEach(b => {
                    const r = b.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) return;
                    const aria = b.getAttribute('aria-label') || '';
                    const txt = (b.innerText || '').trim().slice(0, 60);
                    if (!aria && !txt) return;
                    const al = (aria + ' ' + txt).toLowerCase();
                    if (!/reagir|like|coment|compart|share|repost/.test(al)) return;
                    out.push({a: aria.slice(0, 120), t: txt, tag: b.tagName, pressed: b.getAttribute('aria-pressed')});
                });
                return out;
            }
        """)

        like_btns = [
            b
            for b in buttons
            if any(k in (b["a"] + " " + b["t"]).lower() for k in ["reagir", "like"])
        ]
        comment_btns = [
            b
            for b in buttons
            if any(k in (b["a"] + " " + b["t"]).lower() for k in ["coment"])
        ]
        share_btns = [
            b
            for b in buttons
            if any(
                k in (b["a"] + " " + b["t"]).lower()
                for k in ["compart", "share", "repost"]
            )
        ]

        log(f"\n--- LIKE buttons ({len(like_btns)}) ---")
        for b in like_btns[:10]:
            log(
                f"  <{b['tag']} pressed={b['pressed']!r}>  aria={b['a']!r}  text={b['t']!r}"
            )

        log(f"\n--- COMMENT buttons ({len(comment_btns)}) ---")
        for b in comment_btns[:10]:
            log(f"  <{b['tag']}>  aria={b['a']!r}  text={b['t']!r}")

        log(f"\n--- SHARE buttons ({len(share_btns)}) ---")
        for b in share_btns[:10]:
            log(f"  <{b['tag']}>  aria={b['a']!r}  text={b['t']!r}")

        log("\n=== FIRST POST HTML (4000 chars) ===")
        log(posts["sample"])

        OUT.write_text("\n".join(lines), encoding="utf-8")
        log(f"\nDump saved to: {OUT}")

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
