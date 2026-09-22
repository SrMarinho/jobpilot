"""Prompt de cura de selector e parsing da resposta. Puro, sem IO.

Separado do resto da cura porque é a parte que mais precisa de teste e a que
menos precisa de browser: dada uma descrição do DOM e a intenção do campo,
monta o pedido e extrai seletores da resposta.

Duas escolhas que valem explicação:

**A intenção vai em português, junto do nome técnico.** "invite modal" não diz
nada sozinho; "container do modal de confirmação que abre depois do clique em
Conectar" diz. Sem isso o modelo recebe uma lista de elementos e um nome em
inglês, e chuta.

**A resposta é uma lista de seletores crus, um por linha.** Nada de JSON: o
formato mais simples possível é o que menos dá errado, e qualquer prosa que
escape é filtrada aqui e, depois, reprovada pela validação na página viva.

O prompt proíbe explicitamente a vírgula de topo. Não é preciosismo: o projeto
já pagou esse bug (``locator("a, b")`` casa os dois e estoura o strict mode do
Playwright) e o registrou em ``selectors.py``. Um LLM que não é avisado
reintroduz isso na primeira oportunidade, porque ``a, b`` é CSS idiomático.
"""

from __future__ import annotations

import re

MAX_CANDIDATES = 3

_FENCE_RE = re.compile(r"^\s*```[a-z]*\s*$", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

_SCOPE_LABEL = {
    "page": "a página inteira",
    "dialog": "o modal/diálogo aberto no momento",
    "card": "um card da lista de resultados",
}


def build_heal_prompt(
    *,
    field: str,
    intent: str,
    scope: str,
    kind: str,
    failed: list[str],
    dom_context: str,
    expect: str | None = None,
    max_matches: int = 1,
) -> str:
    """Pedido de novos candidatos para um campo que parou de resolver."""
    alvo = (
        "um elemento clicável (botão ou link) habilitado"
        if kind == "enabled"
        else "um elemento visível"
    )
    exigencia = (
        f"\n- O nome acessível (aria-label ou texto) do elemento DEVE casar a "
        f"expressão regular: {expect}"
        if expect
        else ""
    )
    quebrados = "\n".join(f"  - {s}" for s in failed) or "  (nenhum declarado)"

    return f"""Você está consertando um seletor de automação web que parou de funcionar.

CAMPO: {field}
O QUE ELE PRECISA ENCONTRAR: {intent}
ESCOPO DA BUSCA: {_SCOPE_LABEL.get(scope, scope)}
TIPO DE ALVO: {alvo}

SELETORES QUE NÃO CASAM MAIS:
{quebrados}

ELEMENTOS PRESENTES NA PÁGINA AGORA:
{dom_context}

TAREFA: proponha de 1 a {MAX_CANDIDATES} seletores novos que encontrem esse
elemento no DOM descrito acima.

REGRAS OBRIGATÓRIAS:
- Um seletor por linha. Nada além dos seletores: sem explicação, sem markdown,
  sem numeração.
- CSS puro, ou XPath prefixado com "xpath=".
- PROIBIDO vírgula no nível de topo do seletor (ex: "a, b"). Isso casa os dois
  seletores ao mesmo tempo e estoura o strict mode do Playwright.
- PROIBIDO seletor genérico sozinho: "div", "span", "button", "*", "body".
- Cada seletor deve casar no máximo {max_matches} elemento(s). Seletor amplo
  demais será rejeitado.
- Prefira, nesta ordem: atributos data-test*/data-*-id, aria-label, role,
  texto estável. Classe ofuscada (ex: "_a3b7x") é último recurso — elas mudam
  a cada deploy do site.
- Use apenas atributos e textos que aparecem na lista de elementos acima. Não
  invente atributo que você não viu.{exigencia}

SELETORES:"""


def parse_candidates(raw: str, *, limit: int = MAX_CANDIDATES) -> list[str]:
    """Seletores extraídos da resposta, na ordem, sem repetição.

    Tolerante de propósito: modelo local devolve ``<think>``, modelo grande
    às vezes embrulha em markdown ou numera. O que escapar daqui ainda passa
    por ``is_safe_candidate`` e pela validação na página viva — este parser não
    é a barreira de segurança, é só o desembrulho.
    """
    if not raw:
        return []

    texto = _THINK_RE.sub(" ", raw)
    saida: list[str] = []
    for linha in texto.splitlines():
        if _FENCE_RE.match(linha):
            continue
        limpa = _BULLET_RE.sub("", linha).strip()
        limpa = limpa.strip("`").strip()
        if not limpa or limpa.startswith("#"):
            continue
        if _parece_prosa(limpa):
            continue
        if limpa not in saida:
            saida.append(limpa)
        if len(saida) >= limit:
            break
    return saida


def _parece_prosa(linha: str) -> bool:
    """Frase em linguagem natural que o modelo insistiu em escrever.

    Seletor pode conter espaço (``div[role='dialog'] button``), então contar
    palavras não serve. O sinal confiável é a ausência de sintaxe de seletor:
    um seletor útil aqui sempre tem ``[``, ``.``, ``#``, ``:`` ou começa com
    ``xpath=``.
    """
    if linha.startswith("xpath="):
        return False
    if any(char in linha for char in "[.#:>"):
        return False
    # Sobra só nome de tag nu ("button") ou prosa ("Aqui estão os seletores").
    return True
