import re

from playwright.async_api import Page

from src.config.settings import logger


# Página de analytics do próprio perfil. Mostra "X visualizações do perfil"
# nos últimos 90 dias. ⚠️ selectors LinkedIn 2026 best-effort.
PROFILE_VIEWS_URL = "https://www.linkedin.com/analytics/profile-views/"


def _to_int(raw: str) -> int | None:
    # "1.234" / "1,234" / "1 234" -> 1234 (separador de milhar em qualquer locale)
    digits = re.sub(r"[.,\s]", "", raw.strip())
    return int(digits) if digits.isdigit() else None


# Número adjacente ao rótulo, antes OU depois ("50 visualizações do perfil" e
# "Visualizações do perfil\n50"). PT + EN.
_PATTERNS = (
    r"([\d.,\s]{1,12})\s*visualizaç\w*\s+do\s+perfil",
    r"visualizaç\w*\s+do\s+perfil[^\d]{0,40}([\d.,\s]{1,12})",
    r"([\d.,\s]{1,12})\s*profile views",
    r"profile views[^\d]{0,40}([\d.,\s]{1,12})",
)


class ProfileViewsPage:
    def __init__(self, page: Page, url: str = PROFILE_VIEWS_URL):
        self.page = page
        self.url = url

    async def goto(self) -> None:
        logger.info(f"Opening profile-views page: {self.url}")
        await self.page.goto(self.url, wait_until="domcontentloaded")
        await self.page.wait_for_timeout(6000)

    async def scrape_with_goto(self) -> int | None:
        await self.goto()
        return await self.scrape()

    async def scrape(self) -> int | None:
        """Retorna a contagem de visualizações (90 dias) ou None."""
        try:
            text = await self.page.evaluate("() => document.body.innerText || ''")
        except Exception as e:
            logger.warning(f"Profile-views page read failed: {e}")
            return None
        low = text.lower()
        if "visualizaç" not in low and "profile views" not in low:
            logger.warning("Profile-views page did not load expected content")
            return None
        for pat in _PATTERNS:
            m = re.search(pat, low)
            if m:
                val = _to_int(m.group(1))
                if val is not None:
                    logger.info(f"Profile views scraped: {val} (90d)")
                    return val
        logger.warning("Profile-views count not found in page text")
        return None
