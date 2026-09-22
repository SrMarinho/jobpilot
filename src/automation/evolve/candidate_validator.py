"""Valida na página viva um candidato proposto pelo LLM.

Esta é a barreira que permite a autonomia. O modelo não decide nada: ele
sugere, e o candidato só é aceito se sobreviver a uma bateria de verificações
contra o DOM real, naquele instante.

**Nunca clica para validar.** Clicar no LinkedIn manda convite, DM ou
denúncia; um teste que age não é teste, é a ação. Tudo aqui é leitura:
contagem, visibilidade, estado habilitado e nome acessível.

A verificação que mais importa é a última. Contagem e visibilidade só dizem
"existe um elemento"; elas não impedem o modelo de devolver o botão
"Denunciar" no lugar de "Enviar convite". O que impede é ``expect``: a regex
que o nome acessível precisa casar, declarada por campo no
``selector_registry``. Campo clicável sem ``expect`` não chega aqui — é
declarado incurável na origem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from playwright.async_api import Locator, Page

from src.config.settings import logger
from src.core.use_cases.evolve.selector_registry import FieldSpec
from src.core.use_cases.evolve.selector_store import is_safe_candidate

# Curto de propósito: o candidato tem que estar visível AGORA, no DOM que o LLM
# acabou de ver. Esperar seria dar tempo de a página mudar e validar outra
# coisa.
_CHECK_TIMEOUT = 1_500

_CLICKABLE_TAGS = {"button", "a", "input"}
_CLICKABLE_ROLES = {"button", "link", "menuitem", "tab"}


@dataclass(frozen=True, slots=True)
class Validation:
    ok: bool
    selector: str
    reason: str = ""
    matches: int = 0
    name: str = ""

    def __bool__(self) -> bool:
        return self.ok


def resolve(root: Page | Locator, selector: str) -> Locator:
    """Locator do seletor, aceitando ``xpath=``. Sem ``.first``.

    A contagem precisa ver **todos** os nós que casam — é assim que um seletor
    amplo demais é pego. Quem quer um nó usa ``.first`` no retorno.
    """
    if selector.startswith("xpath="):
        return root.locator(selector[len("xpath=") :])
    return root.locator(selector)


async def _accessible_name(locator: Locator) -> str:
    """aria-label, senão texto. É o que o usuário leria no elemento."""
    try:
        label = await locator.get_attribute("aria-label")
        if label and label.strip():
            return label.strip()
    except Exception:
        pass
    try:
        text = await locator.inner_text()
        return " ".join(text.split())[:120]
    except Exception:
        return ""


async def validate(
    root: Page | Locator,
    selector: str,
    spec: FieldSpec,
    *,
    kind: str = "visible",
) -> Validation:
    """Aprova ou reprova um candidato, com motivo. Nunca levanta."""
    ok, reason = is_safe_candidate(selector)
    if not ok:
        return Validation(False, selector, f"regra de segurança: {reason}")

    try:
        locator = resolve(root, selector)
        matches = await locator.count()
    except Exception as e:
        return Validation(False, selector, f"seletor inválido: {type(e).__name__}")

    if matches == 0:
        return Validation(False, selector, "não casa nenhum elemento", 0)
    if matches > spec.max_matches:
        # Seletor amplo passaria a contagem por acaso e depois agiria no
        # elemento errado — "o primeiro que casar" deixa de ser previsível.
        return Validation(
            False,
            selector,
            f"casa {matches} elementos (máximo {spec.max_matches})",
            matches,
        )

    first = locator.first
    try:
        if not await first.is_visible(timeout=_CHECK_TIMEOUT):
            return Validation(False, selector, "casa mas não está visível", matches)
    except Exception as e:
        return Validation(
            False,
            selector,
            f"falha ao checar visibilidade: {type(e).__name__}",
            matches,
        )

    name = await _accessible_name(first)

    if kind == "enabled" or spec.clicked:
        try:
            if not await first.is_enabled():
                return Validation(
                    False, selector, "elemento desabilitado", matches, name
                )
        except Exception as e:
            return Validation(
                False,
                selector,
                f"falha ao checar estado: {type(e).__name__}",
                matches,
                name,
            )
        if not await _is_clickable(first):
            return Validation(
                False, selector, "não é elemento clicável (tag/role)", matches, name
            )

    if spec.expect:
        if not re.search(spec.expect, name, re.IGNORECASE):
            # A trava principal: sem isto a automação poderia clicar em
            # "Denunciar" achando que é "Enviar convite".
            return Validation(
                False,
                selector,
                f"nome acessível {name!r} não casa o esperado ({spec.expect})",
                matches,
                name,
            )

    return Validation(True, selector, "", matches, name)


async def _is_clickable(locator: Locator) -> bool:
    try:
        tag = (await locator.evaluate("el => el.tagName.toLowerCase()")) or ""
        if tag in _CLICKABLE_TAGS:
            return True
        role = (await locator.get_attribute("role")) or ""
        return role.lower() in _CLICKABLE_ROLES
    except Exception:
        return False


async def first_valid(
    root: Page | Locator,
    candidates: list[str],
    spec: FieldSpec,
    *,
    kind: str = "visible",
) -> tuple[Validation | None, list[Validation]]:
    """Primeiro candidato aprovado, e o laudo de todos os testados.

    Devolve as reprovações também porque elas são o material de diagnóstico:
    "casa 47 elementos" e "nome acessível 'Denunciar'" contam histórias
    diferentes sobre o que o modelo entendeu errado.
    """
    laudos: list[Validation] = []
    for selector in candidates:
        result = await validate(root, selector, spec, kind=kind)
        laudos.append(result)
        if result.ok:
            return result, laudos
        logger.info(
            f"[evolve] candidato reprovado campo={spec.field!r} "
            f"{selector!r}: {result.reason}"
        )
    return None, laudos
