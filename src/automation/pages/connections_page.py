"""Page object: lê as conexões recentes (My Network → Connections).

Usado pelo follow-up pós-conexão para descobrir quem aceitou um convite.
LinkedIn ordena a lista por "recém-adicionadas" por padrão. Selectors
best-effort (DOM 2026 obfuscado) — ⚠️ não verificado ao vivo.
"""

from playwright.async_api import Page

from src.config.settings import logger

CONNECTIONS_URL = "https://www.linkedin.com/mynetwork/invite-connect/connections/"

# Extrai (name, profile_url, headline) dos cartões de conexão. Caça links de
# perfil (/in/) e sobe pro card pra pegar o headline (texto secundário).
_SCRAPE_JS = """
(limit) => {
    const out = [];
    const seen = new Set();
    const anchors = document.querySelectorAll("a[href*='/in/']");
    for (const a of anchors) {
        const href = (a.href || '').split('?')[0];
        if (!href || seen.has(href)) continue;
        const name = (a.innerText || '').trim().split('\\n')[0].trim();
        if (!name || name.length < 2) continue;
        // Sobe até um container com texto suficiente p/ ter headline.
        let card = a;
        for (let i = 0; i < 6; i++) {
            if (!card.parentElement) break;
            card = card.parentElement;
            if ((card.innerText || '').length > name.length + 10) break;
        }
        const lines = (card.innerText || '')
            .split('\\n').map(s => s.trim()).filter(Boolean);
        const idx = lines.findIndex(l => l.startsWith(name));
        const headline = idx >= 0 && lines[idx + 1] ? lines[idx + 1] : '';
        seen.add(href);
        out.push({ name, profile_url: href, headline });
        if (out.length >= limit) break;
    }
    return out;
}
"""


class ConnectionsPage:
    def __init__(self, page: Page, url: str = CONNECTIONS_URL):
        self.page = page
        self.url = url

    async def goto(self) -> None:
        from src.automation.checkpoint import ensure_not_blocked

        logger.info(f"Abrindo conexões: {self.url}")
        await self.page.goto(self.url, wait_until="domcontentloaded")
        await ensure_not_blocked(self.page, "followup")
        await self.page.wait_for_timeout(2500)

    async def recent_connections(self, limit: int = 10) -> list[dict]:
        await self.goto()
        # Scroll leve pra forçar lazy-load dos primeiros cartões.
        try:
            await self.page.evaluate("window.scrollBy(0, 600)")
            await self.page.wait_for_timeout(1200)
        except Exception:
            pass
        try:
            handle = await self.page.evaluate_handle(_SCRAPE_JS, limit)
            data = await handle.json_value()
        except Exception as e:
            logger.warning(f"Scrape de conexões falhou: {e}")
            return []
        result = [d for d in (data or []) if d.get("profile_url")]
        logger.info(f"Conexões recentes encontradas: {len(result)}")
        return result[:limit]
