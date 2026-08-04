"""Triagem de uma vaga avulsa: abre o link, lê e avalia — sem candidatar.

Existe pro caso "achei essa vaga, vale a pena?": você manda o link no Telegram
e recebe o veredito do LLM com salário estimado e gaps de skill, sem passar
pelo pipeline de busca inteiro.

O resultado entra no mesmo histórico do `jobs apply`, então a vaga aparece na
fila (`jobs queue`) e não é reavaliada depois.
"""

import re
from dataclasses import dataclass

from src.automation.pages.indeed_jobs_page import IndeedJobsPage
from src.automation.pages.jobs_search_page import JobsSearchPage
from src.automation.tasks.job_application_manager import detect_site
from src.config.settings import logger
from src.core.entities.eval_result import EvalResult
from src.core.entities.evaluated_job import EvaluatedJob
from src.core.use_cases.applied_jobs_tracker import AppliedJobsTracker
from src.core.use_cases.evaluated_jobs_tracker import EvaluatedJobsTracker
from src.core.use_cases.job_evaluator import JobEvaluator


@dataclass(slots=True)
class TriageResult:
    url: str
    site: str
    title: str = ""
    company: str = ""
    description: str = ""
    result: EvalResult | None = None
    from_cache: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.result is not None

    def as_telegram(self) -> str:
        if self.error:
            return f"⚠️ <b>Triagem falhou</b>\n{self.error}\n{self.url}"

        veredito = "✅ <b>Match</b>" if self.result.matches else "❌ <b>Não bate</b>"
        linhas = [f"{veredito} — {self.site}"]
        if self.title:
            linhas.append(f"📋 <b>{self.title}</b>")
        if self.company:
            linhas.append(f"🏢 {self.company}")
        if self.result.salary:
            salario = f"{self.result.salary:,}".replace(",", ".")
            linhas.append(f"💰 R$ {salario}{self.result.contract_tag}")
        if self.result.reason:
            linhas.append(f"\n💬 {self.result.reason}")
        if self.result.missing_skills:
            gaps = ", ".join(self.result.missing_skills[:6])
            linhas.append(f"\n🎯 <b>Gaps:</b> {gaps}")
        if self.from_cache:
            linhas.append("\n<i>(avaliação reaproveitada do histórico)</i>")
        linhas.append(f"\n🔗 {self.url}")
        return "\n".join(linhas)


_LINKEDIN_JOB_ID = re.compile(r"linkedin\.com/jobs/view/(\d+)", re.IGNORECASE)


def readable_url(url: str) -> str:
    """URL da mesma vaga, num layout que dá pra scrapear.

    A página ``/jobs/view/<id>/`` do LinkedIn é montada com classes hashadas
    (``_55650414``, ``a955a297``) que mudam a cada deploy — não há selector
    estável ali. A mesma vaga aberta como ``/jobs/search/?currentJobId=<id>``
    cai no painel de detalhe da busca, que é o layout que ``JobsSearchPage``
    já sabe ler. Então redirecionamos em vez de perseguir hash.
    """
    match = _LINKEDIN_JOB_ID.search(url)
    if not match:
        return url
    return f"https://www.linkedin.com/jobs/search/?currentJobId={match.group(1)}"


async def _read_job(page, url: str, site: str) -> tuple[str, str, str]:
    """Título, empresa e descrição da página da vaga."""
    page_obj = (
        IndeedJobsPage(page, url) if site == "indeed" else JobsSearchPage(page, url)
    )
    title = await page_obj.get_job_title()
    company = await page_obj.get_company_name()
    description = await page_obj.get_job_description()
    return title, company, description


async def triage_job(
    page,
    url: str,
    *,
    evaluator: JobEvaluator,
    evaluations: EvaluatedJobsTracker | None = None,
    tracker: AppliedJobsTracker | None = None,
    use_cache: bool = True,
) -> TriageResult:
    """Avalia uma vaga a partir do link. Não clica em aplicar."""
    evaluations = evaluations or EvaluatedJobsTracker()
    tracker = tracker or AppliedJobsTracker()
    site = detect_site(url)
    job_id = tracker._job_id(url)
    triage = TriageResult(url=url, site=site)

    if use_cache:
        cached = evaluations.cached_result(job_id)
        if cached is not None:
            known = evaluations.get(job_id)
            triage.title = known.title if known else ""
            triage.company = known.company if known else ""
            triage.result = cached
            triage.from_cache = True
            logger.info(f"Triagem: veredito reaproveitado p/ {url}")
            return triage

    try:
        target = readable_url(url)
        await page.goto(target, wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        title, company, description = await _read_job(page, target, site)
    except Exception as e:
        triage.error = f"não consegui abrir/ler a vaga: {e}"
        logger.warning(f"Triagem falhou em {url}: {e}")
        return triage

    if not title and not description:
        # Sem conteúdo o LLM avaliaria o vazio e devolveria um "não" sem base.
        triage.error = (
            "página sem título nem descrição (login expirado ou vaga fora do ar?)"
        )
        return triage

    triage.title, triage.company, triage.description = title, company, description
    triage.result = await evaluator.evaluate_async(title, description)

    try:
        evaluations.save(
            EvaluatedJob.create(
                job_id, url, title, triage.result, company=company, site=site
            )
        )
    except Exception as e:
        logger.warning(f"Falha ao guardar triagem: {e}")
    return triage
