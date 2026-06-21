"""Page object: descoberta de contratações recentes via posts de anúncio.

Método escolhido no spike (`scripts/spike_hired.py`): o content-search de
LinkedIn por frases de anúncio ("comecei como"/"started a new position"),
ordenado por data, entrega contratações recentes com recência grátis (data do
post). O perfil do autor é aberto só p/ enriquecer skills (bloco inline
"Principais competências", legível mesmo em perfil 2º/3º grau truncado).

⚠️ Selectors LinkedIn 2026 best-effort (DOM obfuscado).
"""

from playwright.async_api import Page

from src.config.settings import logger
from src.automation.checkpoint import ensure_not_blocked

# Raspa blocos de POST do content-search: sobe da âncora /in/ até o bloco com
# texto longo (corpo do post). Retorna autor, url do perfil e texto do post.
_POSTS_JS = """
(limit) => {
    const out = [];
    const seen = new Set();
    const anchors = document.querySelectorAll("a[href*='/in/']");
    for (const a of anchors) {
        const href = (a.href || '').split('?')[0];
        if (!href || seen.has(href)) continue;
        const author = (a.innerText || '').trim().split('\\n')[0].trim();
        if (!author || author.length < 2) continue;
        let block = a;
        for (let i = 0; i < 10; i++) {
            if (!block.parentElement) break;
            block = block.parentElement;
            if ((block.innerText || '').length > 200) break;
        }
        const text = (block.innerText || '').slice(0, 900);
        if (text.length < 120) continue;
        seen.add(href);
        out.push({ author, profile_url: href, text });
        if (out.length >= limit) break;
    }
    return out;
}
"""

# Skills inline do perfil: bloco "Principais competências"/"Top skills" (não é
# heading; vem como texto no card de intro), skills separadas por " · ".
_PROFILE_JS = r"""
() => {
    const body = document.body.innerText || '';
    const m = body.match(/Principais compet\S*ncias\s*\n+([^\n]{2,200})/i)
           || body.match(/Top skills\s*\n+([^\n]{2,200})/i);
    const skillsLine = m ? m[1].trim() : '';
    const h1 = document.querySelector('main h1');
    const headline = (() => {
        if (!h1) return '';
        const card = h1.closest('section') || h1.parentElement;
        return card ? (card.innerText || '').slice(0, 300) : (h1.innerText || '');
    })();
    // Miolo do perfil p/ o LLM extrair skills (headline + sobre + competências
    // + em destaque). Corta o topo (nav) e limita o tamanho.
    const profileText = body.replace(/^[\s\S]*?Reative o Premium\s*/i, '').slice(0, 2000);
    return { skills_line: skillsLine, headline, profile_text: profileText };
}
"""


def _split_skills(line: str) -> list[str]:
    if not line:
        return []
    skills = [skill.strip() for skill in line.replace("•", "·").split("·")]
    return [skill for skill in skills if 1 < len(skill) < 60]


class HiredPostPage:
    def __init__(self, page: Page):
        self.page = page

    async def scrape_posts(self, url: str, limit: int) -> list[dict]:
        """Abre a busca de anúncios e raspa blocos de post. 1 goto."""
        try:
            await self.page.goto(url, wait_until="domcontentloaded")
            await self.page.wait_for_timeout(3500)
            await ensure_not_blocked(self.page, "hired_posts")
            for _ in range(4):
                await self.page.evaluate("window.scrollBy(0, 1200)")
                await self.page.wait_for_timeout(1000)
        except Exception as e:
            from src.automation.checkpoint import CheckpointError

            if isinstance(e, CheckpointError):
                raise
            logger.warning(f"scrape_posts goto/scroll falhou: {e}")
            return []
        try:
            handle = await self.page.evaluate_handle(_POSTS_JS, limit)
            posts = await handle.json_value()
        except Exception as e:
            logger.warning(f"scrape_posts evaluate falhou: {e}")
            posts = []
        valid_posts = [post for post in (posts or []) if post.get("profile_url")]
        logger.info(f"Posts de anúncio encontrados: {len(valid_posts)}")
        return valid_posts

    async def scrape_profile_skills(self, profile_url: str) -> dict:
        """Abre o perfil e extrai skills inline + headline. Best-effort.

        Retorna ``{"top_skills": [...], "headline": str, "profile_text": str}``.
        ``top_skills`` (inline) pode vir vazio; ``profile_text`` alimenta o LLM.
        """
        try:
            await self.page.goto(profile_url, wait_until="domcontentloaded")
            await self.page.wait_for_timeout(2800)
            await ensure_not_blocked(self.page, "hired_profile")
            for _ in range(4):
                await self.page.evaluate("window.scrollBy(0, 900)")
                await self.page.wait_for_timeout(600)
        except Exception as e:
            from src.automation.checkpoint import CheckpointError

            if isinstance(e, CheckpointError):
                raise
            logger.warning(f"scrape_profile_skills goto falhou {profile_url}: {e}")
            return {"top_skills": [], "headline": "", "profile_text": ""}
        try:
            data = await self.page.evaluate(_PROFILE_JS)
        except Exception as e:
            logger.warning(f"scrape_profile_skills evaluate falhou: {e}")
            return {"top_skills": [], "headline": "", "profile_text": ""}
        return {
            "top_skills": _split_skills(data.get("skills_line", "")),
            "headline": (data.get("headline", "") or "").strip()[:200],
            "profile_text": (data.get("profile_text", "") or "").strip(),
        }
