"""Insere um selector aprendido na constante da page, sem LLM.

Promover um candidato validado é edição mecânica: a constante é uma
``list[str]`` em nível de módulo e o candidato entra como primeiro item. Não há
julgamento envolvido, então não há motivo pra pagar um LLM — e cada uso de LLM
com permissão de escrita é um grau de liberdade a mais num sistema autônomo.

O parsing é por texto e não por AST de propósito: ``ast`` sabe ler, mas não
sabe reescrever preservando comentários e formatação, e as listas de candidatos
são cheias de comentário explicando por que cada fallback existe. Reescrever
via AST perderia justamente a documentação que faz essas listas serem
legíveis.

Quando o padrão não casa (constante numa linha só, formato inesperado), a
função devolve ``None`` em vez de improvisar. Aí o caminho é o ``claude -p``,
que aguenta o caso irregular — o mecânico cobre o comum, o caro cobre o resto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EditResult:
    ok: bool
    content: str = ""
    reason: str = ""
    added_lines: int = 0

    def __bool__(self) -> bool:
        return self.ok


def _block_pattern(constant: str) -> re.Pattern:
    """Bloco ``_CONST = [ ... ]`` multi-linha, com o fecho na coluna zero."""
    return re.compile(
        rf"^(?P<head>{re.escape(constant)}\s*(?::\s*[^=]+)?=\s*\[\s*\n)"
        rf"(?P<body>.*?)"
        rf"(?P<tail>^\]\s*$)",
        re.MULTILINE | re.DOTALL,
    )


def _indent_of(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped:
            return line[: len(line) - len(line.lstrip())] or "    "
    return "    "


def _literal(selector: str) -> str:
    """Literal na aspa que o ``ruff format`` usaria.

    Aspa dupla por padrão, porque é o que o formatter do projeto normaliza — e
    um patch que sai com aspa simples é reprovado pelo gate
    ``ruff format --check`` sem ter nada de errado.

    Aspa simples só quando o seletor contém aspa dupla
    (``[aria-label="x"]``); seletor com as duas cai no ``repr``, que escapa o
    necessário.
    """
    if '"' not in selector:
        return '"' + selector + '"'
    if "'" not in selector:
        return "'" + selector + "'"
    return repr(selector)


def insert_candidate(
    source: str,
    constant: str,
    selector: str,
    *,
    note: str = "",
) -> EditResult:
    """Coloca ``selector`` como primeiro item da constante.

    Primeiro e não último porque a ordem é de preferência: o aprendido é o
    layout de hoje, e os declarados abaixo dele passam a ser o fallback
    histórico — a mesma ordem que o resolver já usa em runtime.
    """
    if not selector.strip():
        return EditResult(False, reason="selector vazio")

    match = _block_pattern(constant).search(source)
    if match is None:
        return EditResult(
            False,
            reason=(
                f"não achei o bloco `{constant} = [...]` multi-linha "
                "(constante numa linha só ou formato inesperado)"
            ),
        )

    body = match.group("body")
    literal = _literal(selector)
    if literal in body or selector in body:
        return EditResult(False, reason="selector já está na constante")

    indent = _indent_of(body)
    comentario = f"{indent}# {note}\n" if note else ""
    nova_linha = f"{comentario}{indent}{literal},\n"

    inicio, fim = match.span()
    trecho = match.group("head") + nova_linha + body + match.group("tail")
    return EditResult(
        True,
        content=source[:inicio] + trecho + source[fim:],
        added_lines=nova_linha.count("\n"),
    )


def promotion_note(*, day: str, reason: str = "cura automática") -> str:
    """Comentário que marca a linha como aprendida, com data.

    Serve pra quem lê o arquivo depois entender por que aquele candidato está
    na frente — e pra saber que ele veio de runtime, não de alguém inspecionando
    o DOM.
    """
    return f"aprendido em {day} pelo evolve ({reason})"
