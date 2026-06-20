import re

from playwright.async_api import Page

from src.config.settings import logger


SSI_URL = "https://www.linkedin.com/sales/ssi"

# Pillar label (PT + EN fragments) -> canonical key
_PILLARS = {
    "brand": ("marca profissional", "professional brand"),
    "find_people": ("pessoas certas", "right people"),
    "engage_insights": ("oferecendo insights", "with insights", "engage with insights"),
    "relationships": ("relacionamentos", "relationships"),
}


def _to_float(raw: str) -> float | None:
    raw = raw.strip()
    # Mixed locale: components use comma decimal ("8,375"), charts use dot
    # decimal ("0.3"). If comma present, it's the decimal sep (drop dots as
    # thousands). Else dot is the decimal sep.
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


class SSIPage:
    def __init__(self, page: Page, url: str = SSI_URL):
        self.page = page
        self.url = url

    async def goto(self) -> None:
        logger.info(f"Opening SSI page: {self.url}")
        await self.page.goto(self.url, wait_until="domcontentloaded")
        await self.page.wait_for_timeout(8000)

    async def scrape_with_goto(self) -> dict | None:
        await self.goto()
        return await self.scrape()

    async def scrape(self) -> dict | None:
        """Returns {total, brand, find_people, engage_insights, relationships,
        rank_industry_pct, rank_network_pct} or None if not parseable."""
        try:
            text = await self.page.evaluate("() => document.body.innerText || ''")
        except Exception as e:
            logger.warning(f"SSI page read failed: {e}")
            return None
        if "social selling index" not in text.lower():
            logger.warning("SSI page did not load expected content")
            return None

        result: dict = {}
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

        # The official "your score" section lists each pillar as
        # "<value>  <label>" (value FIRST). The peer-comparison charts list
        # "<label>\t<value>" (label first) with DIFFERENT averages — must not
        # be matched. So we only accept lines that START with the number.
        value_first = re.compile(r"^(\d+[.,]\d+|\d+)\s+(.+)$")
        for key, fragments in _PILLARS.items():
            for ln in lines:
                m = value_first.match(ln)
                if not m:
                    continue
                label = m.group(2).lower()
                if any(f in label for f in fragments):
                    val = _to_float(m.group(1))
                    if val is not None and val <= 25:
                        result[key] = round(val, 2)
                        break

        pillars = ["brand", "find_people", "engage_insights", "relationships"]
        if not all(k in result for k in pillars):
            logger.warning(f"SSI pillars incomplete: {result}")
            # Still attempt total below; partial data not stored
            return None

        # Total = sum of pillars (each 0-25, total 0-100)
        result["total"] = round(sum(result[k] for k in pillars), 1)

        # Ranks: "Primeiros 83%" (industry) then "Primeiros 90%" (network)
        ranks = re.findall(r"[Pp]rimeiros?\s+(\d+)%|[Tt]op\s+(\d+)%", text)
        flat = [int(a or b) for a, b in ranks]
        if len(flat) >= 1:
            result["rank_industry_pct"] = flat[0]
        if len(flat) >= 2:
            result["rank_network_pct"] = flat[1]

        logger.info(
            f"SSI scraped: total={result['total']} "
            f"(brand={result['brand']}, people={result['find_people']}, "
            f"insights={result['engage_insights']}, rel={result['relationships']})"
        )
        return result
