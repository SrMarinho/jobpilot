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

**Autoevolução.** Este módulo é o único ponto por onde toda resolução passa, e
por isso é onde a cura se enxerta, de duas formas:

1. Candidatos **aprendidos** em runtime entram na frente dos declarados. Vão
   com ``T_FAST`` porque um aprendido obsoleto custa 1s, não 5s, e são o layout
   de hoje — o declarado é o de quando o código foi escrito.
2. Um **gancho de cura** opcional é chamado quando nada casou. Sem gancho
   instalado o comportamento é idêntico ao de antes desta feature. Quem sabe o
   que é LLM e DOM é ``src/automation/evolve/``; aqui só existe o ponto de
   enxerto, senão este resolvedor quase-puro passaria a arrastar Playwright
   pesado e provider de LLM para dentro de 4 page objects.

Nada disso pode quebrar scraping: toda a contabilidade e a cura rodam sob
``except`` amplo e, na dúvida, o caminho é o de sempre.
"""

import os
from collections.abc import Awaitable, Callable

from playwright.async_api import Locator, Page

from src.config.settings import logger

# Timeouts nomeados — evita números mágicos espalhados pelas pages.
T_FAST = 1_000  # elemento que ou já está lá, ou não interessa
T_NORMAL = 5_000  # conteúdo que carrega junto com a página
T_SLOW = 15_000  # navegação/render pesado (lista de vagas, feed)

# Selector que não casa nada. Usado só pela injeção de falha (ver
# `_declared_for`): é como se testa a cura de ponta a ponta sem esperar o
# LinkedIn quebrar de verdade.
_DEAD_SELECTOR = "[data-jp-fault='1']"

HealHook = Callable[..., Awaitable[Locator | None]]
_HEAL_HOOK: HealHook | None = None


def set_heal_hook(hook: HealHook | None) -> None:
    """Instala o gancho chamado quando nenhum candidato casa.

    Assinatura esperada: ``hook(root, selectors, field=..., kind=...)``,
    devolvendo um ``Locator`` já validado ou ``None``.
    """
    global _HEAL_HOOK
    _HEAL_HOOK = hook


def clear_heal_hook() -> None:
    set_heal_hook(None)


def heal_hook_installed() -> bool:
    return _HEAL_HOOK is not None


def _resolve(root: Page | Locator, selector: str) -> Locator:
    """Locator do candidato, aceitando o prefixo ``xpath=``.

    ``.first`` é deliberado: um candidato que casa múltiplos nós é ambiguidade
    do seletor, não erro do chamador — pegar o primeiro é o comportamento útil.
    """
    if selector.startswith("xpath="):
        return root.locator(selector[len("xpath=") :]).first
    return root.locator(selector).first


def _declared_for(field: str, selectors: list[str]) -> list[str]:
    """Candidatos declarados, ou um selector morto sob injeção de falha.

    ``EVOLVE_FAULT_FIELD=<campo>`` simula a quebra de layout daquele campo: os
    declarados são trocados por um selector que não casa nada, o gancho de cura
    dispara de verdade contra o DOM real, e dá pra verificar o laço inteiro sem
    depender de o LinkedIn mudar o HTML. Fica atrás de env var porque é
    ferramenta de verificação, não de produção.
    """
    if os.getenv("EVOLVE_FAULT_FIELD", "").strip() == field:
        logger.warning(f"[evolve] injeção de falha ativa em campo={field!r}")
        return [_DEAD_SELECTOR]
    return selectors


def _candidates(
    field: str, selectors: list[str], timeout: int
) -> list[tuple[str, int, bool]]:
    """``(selector, timeout, aprendido)`` na ordem de tentativa."""
    pairs: list[tuple[str, int, bool]] = []
    for learned in _learned_for(field):
        pairs.append((learned, T_FAST, True))
    for declared in _declared_for(field, selectors):
        pairs.append((declared, timeout, False))
    return pairs


def _learned_for(field: str) -> list[str]:
    try:
        from src.core.use_cases.evolve.selector_store import learned_for

        return learned_for(field)
    except Exception:
        # Store indisponível (import quebrado, doc corrompido) não pode cegar o
        # scraping: sem aprendidos, o comportamento é o de sempre.
        return []


def _note_hit(field: str, selector: str) -> None:
    try:
        from src.core.use_cases.evolve.selector_store import store

        store().record_hit(field, selector)
    except Exception:
        pass


def _note_miss(field: str) -> None:
    try:
        from src.core.use_cases.evolve.selector_store import store

        store().record_miss(field)
    except Exception:
        pass


def flush_learned() -> None:
    """Grava hits/misses acumulados. Chamado no fim do run, não no hot path."""
    try:
        from src.core.use_cases.evolve.selector_store import store

        current = store()
        current.prune()
        current.flush()
    except Exception as e:
        logger.warning(f"[evolve] falha ao gravar contabilidade de selectors: {e}")


async def _try_heal(
    root: Page | Locator, selectors: list[str], *, field: str, kind: str
) -> Locator | None:
    """Chama o gancho de cura, se instalado. Nunca levanta.

    Cura que derruba o run é pior que não curar: o run agendado é a única
    chance do dia.
    """
    if _HEAL_HOOK is None:
        return None
    try:
        return await _HEAL_HOOK(root, selectors, field=field, kind=kind)
    except Exception as e:
        logger.warning(f"[evolve] gancho de cura falhou campo={field!r}: {e}")
        return None


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
    ``required=False`` silencia o WARNING para campos legitimamente opcionais —
    e também desliga a cura, porque ausência esperada não é quebra (é o caso do
    modal de convite, que o LinkedIn deixou de abrir).
    """
    for selector, candidate_timeout, learned in _candidates(field, selectors, timeout):
        try:
            locator = _resolve(root, selector)
            if await locator.is_visible(timeout=candidate_timeout):
                if learned:
                    _note_hit(field, selector)
                return locator
        except Exception:
            continue

    _note_miss(field)
    if not required:
        return None

    healed = await _try_heal(root, selectors, field=field, kind="visible")
    if healed is not None:
        return healed

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
    for selector, candidate_timeout, learned in _candidates(field, selectors, timeout):
        try:
            locator = _resolve(root, selector)
            if (
                await locator.is_visible(timeout=candidate_timeout)
                and await locator.is_enabled()
            ):
                if learned:
                    _note_hit(field, selector)
                return locator
        except Exception:
            continue

    _note_miss(field)
    if not required:
        return None

    healed = await _try_heal(root, selectors, field=field, kind="enabled")
    if healed is not None:
        return healed

    logger.warning(f"Botão não resolveu: campo={field!r} — layout pode ter mudado")
    return None
