"""Resolução de selectors com fallback explícito.

Os job boards trocam classes ofuscadas sem aviso (``.job_seen_beacon``,
``[class*=JobDetails_jobDescription]``), então cada campo é declarado como uma
lista de candidatos em ordem de preferência. Antes isso era copiado ~15 vezes
pelas pages, em quatro idiomas diferentes e com timeouts mágicos espalhados —
e o pior deles, ``locator("a, b")``, casa os DOIS seletores de uma vez e estoura
strict mode quando as duas variantes coexistem, falha que o ``except`` genérico
escondia como "campo vazio".

Aqui a resolução é única, o primeiro candidato visível vence, e quando NENHUM
casa isso vira um WARNING nomeado — o sinal que o canário de selectors consome
pra avisar de quebra antes do run agendado morrer.
"""

from playwright.async_api import Locator, Page

from src.config.settings import logger

# Timeouts nomeados — evita números mágicos espalhados pelas pages.
T_FAST = 1_000  # elemento que ou já está lá, ou não interessa
T_NORMAL = 5_000  # conteúdo que carrega junto com a página
T_SLOW = 15_000  # navegação/render pesado (lista de vagas, feed)


def _resolve(root: Page | Locator, selector: str) -> Locator:
    """Locator do candidato, aceitando o prefixo ``xpath=``.

    ``.first`` é deliberado: um candidato que casa múltiplos nós é ambiguidade
    do seletor, não erro do chamador — pegar o primeiro é o comportamento útil.
    """
    if selector.startswith("xpath="):
        return root.locator(selector[len("xpath=") :]).first
    return root.locator(selector).first


async def first_visible(
    root: Page | Locator,
    selectors: list[str],
    *,
    field: str,
    timeout: int = T_NORMAL,
    required: bool = True,
) -> Locator | None:
    """Primeiro candidato visível da lista, ou ``None``.

    ``field`` nomeia o campo no log de falha ("job title", "apply button").
    ``required=False`` silencia o WARNING para campos legitimamente opcionais.
    """
    for selector in selectors:
        try:
            locator = _resolve(root, selector)
            if await locator.is_visible(timeout=timeout):
                return locator
        except Exception:
            continue
    if required:
        logger.warning(
            f"Selector não resolveu: campo={field!r} "
            f"({len(selectors)} candidatos testados) — layout pode ter mudado"
        )
    return None


async def text_or_empty(
    root: Page | Locator,
    selectors: list[str],
    *,
    field: str,
    timeout: int = T_NORMAL,
    required: bool = True,
) -> str:
    """Texto do primeiro candidato visível, ou ``""``."""
    locator = await first_visible(
        root, selectors, field=field, timeout=timeout, required=required
    )
    if locator is None:
        return ""
    try:
        return (await locator.inner_text()).strip()
    except Exception as e:
        logger.warning(f"Falha ao ler texto de {field!r}: {e}")
        return ""


async def attr_or_none(
    root: Page | Locator,
    selectors: list[str],
    attribute: str,
    *,
    field: str,
    timeout: int = T_FAST,
    required: bool = False,
) -> str | None:
    """Atributo do primeiro candidato visível, ou ``None``."""
    locator = await first_visible(
        root, selectors, field=field, timeout=timeout, required=required
    )
    if locator is None:
        return None
    try:
        return await locator.get_attribute(attribute)
    except Exception:
        return None


async def first_enabled(
    root: Page | Locator,
    selectors: list[str],
    *,
    field: str,
    timeout: int = T_FAST,
    required: bool = True,
) -> Locator | None:
    """Primeiro candidato visível **e** habilitado — para botões clicáveis."""
    for selector in selectors:
        try:
            locator = _resolve(root, selector)
            if await locator.is_visible(timeout=timeout) and await locator.is_enabled():
                return locator
        except Exception:
            continue
    if required:
        logger.warning(f"Botão não resolveu: campo={field!r} — layout pode ter mudado")
    return None
