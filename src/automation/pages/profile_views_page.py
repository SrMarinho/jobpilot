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
# "Visualizações do perfil\n50"). PT + EN. Wording 2026: "Quem viu seu perfil
# nos últimos 90 dias" com o número ANTES do rótulo ("... 90 dias 77 Quem viu
# seu perfil nos últimos 90 dias") — só a variante número-antes é segura, a
# número-depois casaria o "90" de "últimos 90 dias".
_PATTERNS = (
    r"([\d.,\s]{1,12})\s*visualizaç\w*\s+do\s+perfil",
    r"visualizaç\w*\s+do\s+perfil[^\d]{0,40}([\d.,\s]{1,12})",
    r"([\d.,\s]{1,12})\s*profile views",
    r"profile views[^\d]{0,40}([\d.,\s]{1,12})",
    r"([\d.,\s]{1,12})\s*quem\s+viu\s+seu\s+perfil",
    r"([\d.,\s]{1,12})\s*who\s+viewed\s+your\s+profile",
)


class ProfileViewsPage:
    def __init__(self, page: Page, url: str = PROFILE_VIEWS_URL):
        self.page = page
        self.url = url

    async def goto(self) -> None:
        logger.info(f"Opening profile-views page: {self.url}")
        await self.page.goto(self.url, wait_until="domcontentloaded")
        await self._wait_for_content()

    async def _wait_for_content(self, timeout_ms: int = 30000) -> None:
        # Conteúdo é renderizado via JS após o domcontentloaded; o rótulo só
        # monta quando o bloco entra na viewport. Faz scroll progressivo
        # enquanto espera o rótulo aparecer (lazy-render), em vez de sleep fixo.
        deadline = timeout_ms
        step = 600
        found = False
        while deadline > 0:
            found = await self.page.evaluate(
                """() => {
                    const t = (document.body.innerText || '').toLowerCase();
                    return t.includes('visualiza') || t.includes('profile views')
                        || t.includes('quem viu') || t.includes('who viewed');
                }"""
            )
            if found:
                break
            await self.page.evaluate("() => window.scrollBy(0, window.innerHeight)")
            await self.page.wait_for_timeout(step)
            deadline -= step
        if not found:
            logger.warning("Profile-views content wait timed out; scraping anyway")
        # volta ao topo (números principais ficam no topo) e deixa assentar
        await self.page.evaluate("() => window.scrollTo(0, 0)")
        await self.page.wait_for_timeout(1500)

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
        if (
            "visualizaç" not in low
            and "profile views" not in low
            and "quem viu" not in low
            and "who viewed" not in low
        ):
            # diagnóstico: revela redirect/paywall/wording novo na próxima run
            try:
                cur = self.page.url
            except Exception:
                cur = "?"
            snippet = re.sub(r"\s+", " ", text).strip()[:300]
            logger.warning(
                f"Profile-views page did not load expected content "
                f"(url={cur}); text head: {snippet!r}"
            )
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
