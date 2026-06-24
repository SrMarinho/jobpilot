import re

from playwright.async_api import Page

from src.config.settings import logger


# Página de analytics "aparições em pesquisas". Mostra quantas vezes o perfil
# apareceu em resultados de busca na última semana. ⚠️ selectors LinkedIn 2026
# best-effort (mesmo padrão de profile_views_page).
SEARCH_APPEARANCES_URL = "https://www.linkedin.com/analytics/search-appearances"


def _to_int(raw: str) -> int | None:
    # "1.234" / "1,234" / "1 234" -> 1234 (separador de milhar em qualquer locale)
    digits = re.sub(r"[.,\s]", "", raw.strip())
    return int(digits) if digits.isdigit() else None


# Número adjacente ao rótulo, antes OU depois ("14 Ocorrências em resultados de
# pesquisa" e "Ocorrências em resultados de pesquisa\n14"). PT + EN.
_PATTERNS = (
    r"([\d.,\s]{1,12})\s*ocorr\w*\s+em\s+resultados?\s+de\s+pesquisa",
    r"ocorr\w*\s+em\s+resultados?\s+de\s+pesquisa[^\d]{0,40}([\d.,\s]{1,12})",
    r"([\d.,\s]{1,12})\s*apariç\w*\s+em\s+pesquisa",
    r"apariç\w*\s+em\s+pesquisa[^\d]{0,40}([\d.,\s]{1,12})",
    r"([\d.,\s]{1,12})\s*search appearances",
    r"search appearances[^\d]{0,40}([\d.,\s]{1,12})",
)


class SearchAppearancesPage:
    def __init__(self, page: Page, url: str = SEARCH_APPEARANCES_URL):
        self.page = page
        self.url = url

    async def goto(self) -> None:
        logger.info(f"Opening search-appearances page: {self.url}")
        await self.page.goto(self.url, wait_until="domcontentloaded")
        await self._wait_for_content()

    async def _wait_for_content(self, timeout_ms: int = 30000) -> None:
        # Conteúdo renderizado via JS após domcontentloaded; espera o rótulo
        # aparecer em vez de sleep fixo.
        try:
            await self.page.wait_for_function(
                """() => {
                    const t = (document.body.innerText || '').toLowerCase();
                    return t.includes('resultados de pesquisa')
                        || t.includes('apariç')
                        || t.includes('search appearances');
                }""",
                timeout=timeout_ms,
            )
        except Exception:
            logger.warning("Search-appearances content wait timed out; scraping anyway")
        await self.page.wait_for_timeout(1500)

    async def scrape_with_goto(self) -> int | None:
        await self.goto()
        return await self.scrape()

    async def scrape(self) -> int | None:
        """Retorna a contagem de aparições em pesquisas (última semana) ou None."""
        try:
            text = await self.page.evaluate("() => document.body.innerText || ''")
        except Exception as e:
            logger.warning(f"Search-appearances page read failed: {e}")
            return None
        low = text.lower()
        if (
            "resultados de pesquisa" not in low
            and "apariç" not in low
            and "search appearances" not in low
        ):
            logger.warning("Search-appearances page did not load expected content")
            return None
        for pat in _PATTERNS:
            m = re.search(pat, low)
            if m:
                val = _to_int(m.group(1))
                if val is not None:
                    logger.info(f"Search appearances scraped: {val}")
                    return val
        logger.warning("Search-appearances count not found in page text")
        return None
