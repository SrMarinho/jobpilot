"""Canário de selectors: descobre quebra de layout antes do run agendado.

O maior risco operacional do projeto é o job board mudar o HTML. Classes como
``.job_seen_beacon`` ou ``[class*=JobDetails_jobDescription]`` são ofuscadas e
trocam sem aviso — e a falha é silenciosa: o scraper devolve string vazia, o
LLM avalia uma vaga sem descrição, e você só descobre olhando resultado ruim
dias depois.

O canário abre cada página crítica e confirma que os selectors ainda resolvem.
Roda em minutos, sem agir em nada, e avisa no Telegram quando algo some.
"""

from dataclasses import dataclass, field

from src.config.settings import logger


@dataclass(slots=True)
class ProbeResult:
    """Resultado de uma verificação de campo."""

    page: str
    field: str
    ok: bool
    detail: str = ""

    @property
    def label(self) -> str:
        return f"{self.page}.{self.field}"


@dataclass(slots=True)
class CanaryReport:
    results: list[ProbeResult] = field(default_factory=list)

    def add(self, page: str, field_name: str, ok: bool, detail: str = "") -> None:
        result = ProbeResult(page, field_name, ok, detail)
        self.results.append(result)
        level = logger.info if ok else logger.warning
        level(f"[canary] {result.label}: {'OK' if ok else 'FALHOU'} {detail}".strip())

    @property
    def failures(self) -> list[ProbeResult]:
        return [r for r in self.results if not r.ok]

    @property
    def healthy(self) -> bool:
        return not self.failures

    def summary(self) -> str:
        total = len(self.results)
        ok = total - len(self.failures)
        return f"{ok}/{total} selectors OK"

    def as_telegram(self) -> str:
        if not self.results:
            return "🔍 <b>Canário de selectors</b>: nada verificado."
        if self.healthy:
            return (
                f"✅ <b>Canário de selectors</b>: {self.summary()}.\n"
                "Nenhuma quebra de layout detectada."
            )
        linhas = "\n".join(
            f"• <code>{r.label}</code>{f' — {r.detail}' if r.detail else ''}"
            for r in self.failures
        )
        return (
            f"🚨 <b>Canário de selectors</b>: {self.summary()}\n\n"
            f"<b>Quebrados:</b>\n{linhas}\n\n"
            "O layout do site provavelmente mudou. Os runs agendados que dependem "
            "desses campos vão falhar em silêncio."
        )


async def _probe_text(report: CanaryReport, page_name: str, field_name: str, coro):
    """Roda um getter de page object e marca OK se veio conteúdo."""
    try:
        value = await coro
    except Exception as e:
        report.add(page_name, field_name, False, f"erro: {type(e).__name__}")
        return
    if isinstance(value, str):
        ok = bool(value.strip())
        detail = "" if ok else "vazio"
    elif isinstance(value, list):
        ok = bool(value)
        detail = f"{len(value)} itens" if ok else "lista vazia"
    else:
        ok = value is not None
        detail = "" if ok else "None"
    report.add(page_name, field_name, ok, detail)


async def check_linkedin_jobs(page, report: CanaryReport, search_url: str) -> None:
    """Busca de vagas do LinkedIn: cards, título, empresa e descrição."""
    from src.automation.pages.jobs_search_page import JobsSearchPage

    jobs_page = JobsSearchPage(page, search_url)
    await page.goto(search_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    cards = await jobs_page.get_job_cards()
    report.add("linkedin_jobs", "job_cards", bool(cards), f"{len(cards)} cards")
    if not cards:
        # Sem card não dá pra checar os campos do detalhe — evita cascata de
        # falso positivo culpando selectors que nem foram exercitados.
        return

    await _probe_text(
        report, "linkedin_jobs", "card_job_url", jobs_page.get_card_job_url(cards[0])
    )
    try:
        await cards[0].click()
        await page.wait_for_timeout(2500)
    except Exception as e:
        report.add("linkedin_jobs", "card_click", False, f"erro: {type(e).__name__}")
        return

    await _probe_text(report, "linkedin_jobs", "job_title", jobs_page.get_job_title())
    await _probe_text(
        report, "linkedin_jobs", "company_name", jobs_page.get_company_name()
    )
    await _probe_text(
        report, "linkedin_jobs", "job_description", jobs_page.get_job_description()
    )


async def check_linkedin_feed(page, report: CanaryReport) -> None:
    """Feed: os posts ainda são encontrados pelo walk-up dos botões?"""
    from src.automation.pages.feed_page import FeedPage

    feed = FeedPage(page)
    try:
        await feed.goto()
        posts = await feed.get_posts()
    except Exception as e:
        report.add("feed", "get_posts", False, f"erro: {type(e).__name__}")
        return
    report.add("feed", "get_posts", bool(posts), f"{len(posts)} posts")
    if posts:
        await _probe_text(report, "feed", "post_urn", feed.get_post_urn(posts[0]))


async def check_linkedin_people(page, report: CanaryReport, search_url: str) -> None:
    """Busca de pessoas: o botão Connect ainda é encontrado?

    O modal de convite fica de fora de propósito: ele só existe depois de
    clicar em Connect, e clicar manda convite de verdade. O que dá pra checar
    sem efeito colateral é o botão — que é onde a quebra costuma começar.
    """
    from src.automation.pages.people_search_page import PeopleSearchPage

    people = PeopleSearchPage(page, search_url)
    try:
        await page.goto(search_url, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)
        btn = await people.get_connect_btn()
    except Exception as e:
        report.add("linkedin_people", "connect_btn", False, f"erro: {type(e).__name__}")
        return
    report.add(
        "linkedin_people",
        "connect_btn",
        btn is not None,
        "" if btn is not None else "nenhum botão Connect na página",
    )


async def check_profile_analytics(page, report: CanaryReport) -> None:
    """Páginas de analytics do perfil (SSI, views, aparições)."""
    from src.automation.pages.profile_views_page import ProfileViewsPage
    from src.automation.pages.search_appearances_page import SearchAppearancesPage
    from src.automation.pages.ssi_page import SSIPage

    for nome, scraper in (
        ("ssi", SSIPage(page)),
        ("profile_views", ProfileViewsPage(page)),
        ("search_appearances", SearchAppearancesPage(page)),
    ):
        await _probe_text(report, "analytics", nome, scraper.scrape_with_goto())
