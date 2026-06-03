"""Inspect LinkedIn people search DOM — dump button structure to file then exit.

Output written to scripts/_linkedin_dump.txt for inspection.
"""

import sys
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

from src.interfaces.cli.persistence import BOT_PROFILE_DIR
from src.automation import url_builder

URL = url_builder.build_linkedin_people_url(["tech", "recruiter"], network="S")
OUT = Path(__file__).resolve().parent / "_linkedin_dump.txt"


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
        try:
            await page.screenshot(
                path=str(Path(__file__).parent / "_linkedin_dump.png"), full_page=False
            )
            log("Screenshot saved: scripts/_linkedin_dump.png")
        except Exception as e:
            log(f"Screenshot failed: {e}")

        # Try scrolling to trigger lazy load
        for _ in range(5):
            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(700)
        await page.wait_for_timeout(1500)

        buttons = await page.evaluate("""
            () => {
                const out = [];
                const sel = 'button, a[role=button], div[role=button], a, [role=button]';
                document.querySelectorAll(sel).forEach(b => {
                    const r = b.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) return;
                    const aria = b.getAttribute('aria-label') || '';
                    const txt = (b.innerText || '').trim().slice(0, 80);
                    if (!aria && !txt) return;
                    out.push({a: aria.slice(0, 120), t: txt, tag: b.tagName, role: b.getAttribute('role') || ''});
                });
                return out;
            }
        """)

        connect_like = [
            b
            for b in buttons
            if any(
                k in (b["a"] + " " + b["t"]).lower()
                for k in ["conec", "connect", "convid", "invit"]
            )
        ]
        more_like = [
            b
            for b in buttons
            if any(k in b["a"].lower() for k in ["mais", "more action", "overflow"])
        ]

        log(f"\n--- CONNECT/INVITE buttons ({len(connect_like)}) ---")
        for b in connect_like[:30]:
            log(f"  <{b['tag']} role={b['role']!r}>  aria={b['a']!r}  text={b['t']!r}")

        log(f"\n--- MORE/OVERFLOW buttons ({len(more_like)}) ---")
        for b in more_like[:10]:
            log(f"  <{b['tag']} role={b['role']!r}>  aria={b['a']!r}  text={b['t']!r}")

        # Specific: anything with "Pendente" or "Conectar" exact text
        pending = [
            b
            for b in buttons
            if "pendente" in b["t"].lower() or "pending" in b["t"].lower()
        ]
        log(f"\n--- PENDING buttons ({len(pending)}) ---")
        for b in pending[:10]:
            log(f"  <{b['tag']} role={b['role']!r}>  aria={b['a']!r}  text={b['t']!r}")

        log(f"\nTotal visible buttons on page: {len(buttons)}")

        cards = await page.evaluate("""
            () => {
                const selectors = [
                    'li.reusable-search__result-container',
                    'li[class*=reusable-search]',
                    'div[data-chameleon-result-urn]',
                    'ul[role=list] > li',
                ];
                for (const sel of selectors) {
                    const els = document.querySelectorAll(sel);
                    if (els.length > 0) {
                        return {sel, count: els.length, sample: els[0].outerHTML.slice(0, 2500)};
                    }
                }
                return {sel: null, count: 0, sample: 'no card selector matched'};
            }
        """)
        log(
            f"\n--- RESULT CARDS — selector: {cards['sel']!r}, count: {cards['count']} ---"
        )
        log("\n=== FIRST CARD HTML (2500 chars) ===")
        log(cards["sample"])

        OUT.write_text("\n".join(lines), encoding="utf-8")
        log(f"\nDump saved to: {OUT}")

        await context.close()


if __name__ == "__main__":
    asyncio.run(main())
