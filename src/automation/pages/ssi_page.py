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

# Rótulos que só aparecem no gráfico de comparação com pares — o valor ao lado
# deles é a média do setor/rede, não o seu. Linha com qualquer um deles é
# descartada antes do match de pilar.
_PEER_MARKERS = (
    "média",
    "media",
    "setor",
    "rede",
    "average",
    "industry",
    "network",
    "peers",
)

# Rótulo-primeiro nunca cruza quebra de linha: no layout 2026 (rótulo, quebra,
# valor do PRÓXIMO pilar) ele casaria o valor errado. Valor-primeiro pode cruzar
# uma quebra — é exatamente o formato do card de score atual.
_LABEL_FIRST = r"{frag}[^\d\n]{{0,40}}(\d+(?:[.,]\d+)?)"
_VALUE_FIRST = r"(\d+(?:[.,]\d+)?)[ \t]*\n?[^\d\n]{{0,40}}{frag}"


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


def _context_lines(text: str, start: int, end: int) -> str:
    """As linhas inteiras que o match tocou.

    O descarte de pares tem que olhar a linha toda: um match que começa no
    rótulo ("Estabelecer sua marca profissional 20,00") não enxerga o
    "Média do setor:" que veio antes dele na mesma linha.
    """
    left = text.rfind("\n", 0, start) + 1
    right = text.find("\n", end)
    if right == -1:
        right = len(text)
    return text[left:right]


def _looks_peer(chunk: str) -> bool:
    low = chunk.lower()
    return any(marker in low for marker in _PEER_MARKERS)


def parse_ssi_text(text: str) -> dict | None:
    """Extrai os pilares do SSI a partir do ``innerText`` da página.

    Função pura — testável sem browser. Devolve ``None`` quando nem o título da
    página bate; devolve o dict (possivelmente parcial) caso contrário.

    Aceita **as duas ordens** de rótulo/valor. O parser antigo exigia
    ``"<valor> <rótulo>"`` na mesma linha, com o número antes, porque em
    2026-06 essa era a única forma que o card de score usava e a restrição
    servia de proteção contra o gráfico de comparação. O layout mudou: o valor
    passou a vir em linha própria, nenhuma linha casou, e o scrape devolveu
    ``{}`` todo dia desde 2026-06-25 sem nunca dizer o porquê. Agora a proteção
    contra o gráfico é por conteúdo da linha (:data:`_PEER_MARKERS`), não por
    ordem.
    """
    if "social selling index" not in text.lower():
        return None

    result: dict = {}
    for key, fragments in _PILLARS.items():
        for fragment in fragments:
            frag = re.escape(fragment)
            for template in (_LABEL_FIRST, _VALUE_FIRST):
                pattern = template.format(frag=frag)
                # finditer, não search: o rótulo aparece várias vezes (card de
                # score, gráfico de pares, legenda) e só uma ocorrência tem o
                # valor certo colado.
                for m in re.finditer(pattern, text, re.IGNORECASE):
                    if _looks_peer(_context_lines(text, m.start(), m.end())):
                        continue
                    val = _to_float(m.group(1))
                    if val is not None and 0 <= val <= 25:
                        result[key] = round(val, 2)
                        break
                if key in result:
                    break
            if key in result:
                break

    # Ranks: "Primeiros 83%" (industry) then "Primeiros 90%" (network)
    ranks = re.findall(r"[Pp]rimeiros?\s+(\d+)%|[Tt]op\s+(\d+)%", text)
    flat = [int(a or b) for a, b in ranks]
    if len(flat) >= 1:
        result["rank_industry_pct"] = flat[0]
    if len(flat) >= 2:
        result["rank_network_pct"] = flat[1]
    return result


class SSIPage:
    def __init__(self, page: Page, url: str = SSI_URL):
        self.page = page
        self.url = url

    async def goto(self) -> None:
        logger.info(f"Opening SSI page: {self.url}")
        await self.page.goto(self.url, wait_until="domcontentloaded")
        await self._wait_for_content()

    async def _wait_for_content(self, timeout_ms: int = 30000) -> None:
        # Mesmo motivo do profile_views_page: o conteúdo monta via JS e só
        # renderiza quando entra na viewport. Sleep fixo de 8s acertava por
        # sorte; o scroll progressivo sai assim que o texto aparece.
        deadline = timeout_ms
        step = 600
        found = False
        while deadline > 0:
            found = await self.page.evaluate(
                """() => {
                    const t = (document.body.innerText || '').toLowerCase();
                    return t.includes('social selling index');
                }"""
            )
            if found:
                break
            await self.page.evaluate("() => window.scrollBy(0, window.innerHeight)")
            await self.page.wait_for_timeout(step)
            deadline -= step
        if not found:
            logger.warning("SSI content wait timed out; scraping anyway")
        await self.page.evaluate("() => window.scrollTo(0, 0)")
        await self.page.wait_for_timeout(1500)

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

        if re.search(r"descontinuad|discontinued", text, re.I):
            logger.info("SSI indisponível: o LinkedIn descontinuou o acesso ao SSI")
            return None

        result = parse_ssi_text(text)
        if result is None:
            self._log_unparsed(text, "conteúdo esperado não encontrado")
            return None

        pillars = ["brand", "find_people", "engage_insights", "relationships"]
        found = [k for k in pillars if k in result]
        # All-or-nothing custava a série inteira quando um pilar mudava de
        # wording. Com 3 de 4 o total sai subestimado, mas a tendência — que é
        # pra que a série serve — continua legível, e o log diz o que faltou.
        if len(found) < 3:
            self._log_unparsed(text, f"pilares incompletos: {result}")
            return None
        if len(found) < len(pillars):
            missing = [k for k in pillars if k not in result]
            logger.warning(f"SSI parcial — pilares ausentes: {missing}")

        # Total = sum of pillars (each 0-25, total 0-100)
        result["total"] = round(sum(result[k] for k in found), 1)

        logger.info(
            f"SSI scraped: total={result['total']} "
            f"(brand={result.get('brand')}, people={result.get('find_people')}, "
            f"insights={result.get('engage_insights')}, "
            f"rel={result.get('relationships')})"
        )
        return result

    def _log_unparsed(self, text: str, reason: str) -> None:
        # O parser antigo logava só o dict vazio. Sem a URL e sem o texto da
        # página não havia como saber se era redirect, paywall ou wording novo
        # — e por isso a falha durou 80 dias sem pista nenhuma no log.
        try:
            cur = self.page.url
        except Exception:
            cur = "?"
        snippet = re.sub(r"\s+", " ", text).strip()[:300]
        logger.warning(
            f"SSI scrape falhou ({reason}; url={cur}); text head: {snippet!r}"
        )
