from src.config.settings import logger
from src.automation.pages.base import BaseJobsPage
from src.automation.pages.selectors import (
    T_FAST,
    T_NORMAL,
    T_SLOW,
    first_enabled,
    text_or_empty,
)

# Candidatos por campo, em ordem de preferência (ver selectors.py).
_CARDS = ".job-card-container"
_TITLE = [
    ".job-details-jobs-unified-top-card__job-title h1",
    ".jobs-unified-top-card__job-title h1",
    "h1.t-24",
]
_COMPANY = [
    ".job-details-jobs-unified-top-card__company-name a",
    ".jobs-unified-top-card__company-name a",
    ".jobs-unified-top-card__subtitle-primary-grouping a",
    ".job-details-jobs-unified-top-card__primary-description a",
]
_DESCRIPTION = ["#job-details", ".jobs-description__content"]
# LinkedIn 2026: o botao virou <a> e o aria-label virou "Usar a candidatura
# simplificada para esta vaga" — minusculo. contains() do XPath e
# case-sensitive, entao o selector antigo (//button + 'Candidatura') nao casava
# nem a tag nem o texto, e toda vaga aprovada parava na fila.
_LOWER = (
    "translate(@aria-label,"
    "'ABCDEFGHIJKLMNOPQRSTUVWXYZÁÉÍÓÚÂÊÔÃÕÇ',"
    "'abcdefghijklmnopqrstuvwxyzáéíóúâêôãõç')"
)
_EASY_APPLY = [
    # aria-label, PT + EN, sem depender de caixa nem da tag.
    f"xpath=//*[(self::button or self::a) and "
    f"(contains({_LOWER},'candidatura simplificada') or contains({_LOWER},'easy apply')) "
    f"and not(contains({_LOWER},'filtro')) and not(contains({_LOWER},'filter'))]",
    # Fallback pelo texto visivel, para quando o aria-label mudar de novo.
    "xpath=//*[(self::button or self::a) and ("
    "normalize-space()='Candidatura simplificada' or normalize-space()='Easy Apply')]",
]


class JobsSearchPage(BaseJobsPage):
    async def get_job_cards(self):
        try:
            await self.page.wait_for_selector(_CARDS, timeout=T_SLOW)
            return await self.page.locator(_CARDS).all()
        except Exception:
            logger.info("No job cards found on page")
            return []

    async def get_card_job_url(self, card) -> str | None:
        try:
            job_id = await card.get_attribute("data-job-id")
            if job_id:
                return f"https://www.linkedin.com/jobs/view/{job_id}/"
            anchor = card.locator("a[href*='/jobs/view/']").first
            href = await anchor.get_attribute("href") or ""
            return href.split("?")[0] if href else None
        except Exception:
            return None

    async def get_job_title(self) -> str:
        return await text_or_empty(
            self.page, _TITLE, field="linkedin job title", timeout=T_SLOW
        )

    async def get_company_name(self) -> str:
        return await text_or_empty(
            self.page, _COMPANY, field="linkedin company name", timeout=T_FAST
        )

    async def get_job_description(self) -> str:
        return await text_or_empty(
            self.page, _DESCRIPTION, field="linkedin job description", timeout=T_NORMAL
        )

    async def get_easy_apply_btn(self):
        # required=False: vaga sem Easy Apply é caso normal, não quebra de layout.
        return await first_enabled(
            self.page, _EASY_APPLY, field="easy apply button", required=False
        )
