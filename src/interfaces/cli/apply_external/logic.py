"""Candidatura manual assistida: resolve o link externo e roda o handler.

Fica fora do agendamento de propósito. O caminho externo envia formulário em
site de terceiro, sem o guard-rail do modal do LinkedIn, e a decisão de rodar é
sempre de quem está olhando.
"""

import json

from src.automation.pages.jobs_search_page import JobsSearchPage
from src.config.settings import logger
from src.core.use_cases import manual_apply
from src.core.use_cases.apply.external_apply import ExternalApplyHandler
from src.core.use_cases.apply.form_extractor import describe_field

# O botão de candidatura externa do LinkedIn abre nova aba. Não confundir com o
# "Candidatura simplificada", que é o Easy Apply e tem caminho próprio.
_LOWER = (
    "translate(@aria-label,"
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÉÍÓÚÂÊÔÃÕÇ',"
    "'abcdefghijklmnopqrstuvwxyzáéíóúâêôãõç')"
)
_EXTERNAL_APPLY_XPATH = (
    "xpath=//*[(self::button or self::a) and "
    f"(contains({_LOWER},'candidatar') or contains({_LOWER},'apply')) "
    f"and not(contains({_LOWER},'simplificada')) "
    f"and not(contains({_LOWER},'easy apply')) "
    f"and not(contains({_LOWER},'filtro')) and not(contains({_LOWER},'filter'))]"
)


def is_job_board_url(url: str) -> bool:
    """``True`` quando a URL é a da vaga no board, não o formulário da empresa."""
    low = url.lower()
    return "linkedin.com/jobs" in low or "indeed.com" in low or "glassdoor.com" in low


async def resolve_external_url(page, job_url: str) -> tuple[str | None, str, str]:
    """Abre a vaga no board e devolve ``(url externa, título, descrição)``.

    O link do formulário da empresa nunca foi guardado em lugar nenhum — o
    ``manual_apply.json`` só tem a URL do board. Aqui ele é resolvido clicando
    no botão de candidatura e capturando a aba que abre, e fica gravado para a
    próxima vez.
    """
    await page.goto(job_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(2500)

    page_obj = JobsSearchPage(page, job_url)
    title = await page_obj.get_job_title()
    description = await page_obj.get_job_description()

    known = manual_apply.get(job_url).get("external_url")
    if known:
        logger.info(f"Link externo já conhecido: {known}")
        return known, title, description

    locator = page.locator(_EXTERNAL_APPLY_XPATH).first
    try:
        if await locator.count() == 0:
            logger.warning("Nenhum botão de candidatura externa na página da vaga")
            return None, title, description
        # href direto quando é <a>: evita depender do popup.
        href = await locator.get_attribute("href")
    except Exception as e:
        logger.warning(f"Botão de candidatura externa não pôde ser lido: {e}")
        return None, title, description

    external: str | None = None
    if href and not is_job_board_url(href):
        external = href
    else:
        try:
            async with page.context.expect_page(timeout=15000) as popup_info:
                await locator.click()
            popup = await popup_info.value
            await popup.wait_for_load_state("domcontentloaded")
            external = popup.url
            await popup.close()
        except Exception as e:
            logger.warning(f"Não consegui capturar a aba do formulário externo: {e}")
            return None, title, description

    if external and is_job_board_url(external):
        logger.warning(f"Link resolvido ainda é do board, não do ATS: {external}")
        return None, title, description
    if external:
        manual_apply.set_external_url(job_url, external)
        logger.info(f"Link externo resolvido: {external}")
    return external, title, description


def print_fields(fields: list[dict]) -> None:
    """Saída do recon: uma linha legível por campo + o JSON cru."""
    print(f"\n===== FORMULÁRIO: {len(fields)} campo(s) =====")
    for field in fields:
        print("  " + describe_field(field))
    print("\n----- JSON -----")
    print(json.dumps(fields, ensure_ascii=False, indent=2))


async def run_external_apply(
    page,
    target_url: str,
    *,
    resume_text: str,
    resume_file: str | None,
    dry_run: bool,
    no_submit: bool,
) -> bool:
    """Um alvo, do link do board (ou direto do ATS) até o envio."""
    job_url = target_url if is_job_board_url(target_url) else ""
    title, description = "", ""

    if job_url:
        external, title, description = await resolve_external_url(page, job_url)
        if not external:
            print("Não consegui resolver o formulário externo dessa vaga.")
            return False
        target_url = external

    await page.goto(target_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    handler = ExternalApplyHandler(
        page,
        resume_text=resume_text,
        resume_file=resume_file,
        job_title=title,
        job_description=description,
        no_submit=no_submit,
    )

    if dry_run:
        print_fields(await handler.inspect())
        return False

    sent = await handler.run()
    if sent and job_url:
        # A fila é do que falta fazer; enviada sai dela.
        manual_apply.mark_applied(job_url)
    return sent
