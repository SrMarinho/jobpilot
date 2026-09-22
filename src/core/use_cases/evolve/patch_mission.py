"""Missão dada ao ``claude -p`` e mensagem de commit. Puro.

O agente que escreve o patch roda sem Bash, num worktree isolado e sem ``.env``
— mas nada disso impede que ele resolva "melhorar" um arquivo vizinho. A missão
é o que estreita o escopo antes de a denylist precisar reprovar: um patch que
mexe no que não devia é trabalho jogado fora, e a missão existe para que isso
não aconteça com frequência.

Instruções escritas aqui, e não improvisadas no ponto de uso, porque são a
parte revisável: dá pra ler o que o agente foi instruído a fazer sem seguir a
execução.
"""

from __future__ import annotations

_REGRAS_COMUNS = """
REGRAS QUE VALEM PARA QUALQUER MUDANÇA:
- Mexa SOMENTE nos arquivos listados em ARQUIVOS PERMITIDOS. Qualquer outro
  arquivo modificado faz o patch inteiro ser descartado.
- NÃO adicione dependência nova (nada de editar pyproject.toml).
- NÃO mexa em .env, .local/, .github/, src/config/, src/core/persistence/,
  src/utils/telegram.py, main.py nem em qualquer arquivo de evolve/.
- Comentário e docstring em português, explicando POR QUE (o motivo que o
  código não mostra), não o que a linha faz.
- Siga o estilo do arquivo: aspas duplas, linha de até 88 colunas.
- O resultado tem que passar `ruff check`, `ruff format --check` e `pytest`.
- Mudança mínima. Não refatore o que está em volta, não renomeie nada, não
  "melhore" o que não foi pedido.
"""


def build_patch_mission(
    *,
    kind: str,
    summary: str,
    detail: str,
    allowed_files: list[str],
    test_hint: str = "",
) -> str:
    """Instruções do patch, prontas pro ``claude -p``."""
    arquivos = "\n".join(f"  - {p}" for p in allowed_files) or "  (nenhum)"
    teste = f"\nTESTE ESPERADO:\n{test_hint}\n" if test_hint else ""
    return f"""Você está corrigindo um problema no projeto JobPilot (Python 3.12,
Playwright, Typer). Trabalhe apenas com Read/Edit/Write/Grep/Glob — você não
tem shell.

TIPO DE CORREÇÃO: {kind}

PROBLEMA:
{summary}

CONTEXTO:
{detail}

ARQUIVOS PERMITIDOS:
{arquivos}
{teste}{_REGRAS_COMUNS}
Faça a correção agora e pare. Não escreva relatório."""


def retire_feature_detail(*, feature: str, evidence: str) -> str:
    """Contexto de um job de aposentadoria de feature morta pela plataforma.

    O caso que motivou: o LinkedIn descontinuou o SSI e a mensagem "Seu acesso
    ao Social Selling Index foi descontinuado" passou a aparecer todo dia. Não
    é selector quebrado nem bug: é uma feature que deixou de existir. Nenhum
    override de banco conserta isso — o conserto é parar de tentar e dizer isso
    uma vez, em vez de avisar para sempre.
    """
    return f"""A plataforma descontinuou "{feature}". Evidência recorrente nos logs:

{evidence}

O que fazer:
1. Detectar a condição de descontinuado UMA vez e registrar o estado, em vez de
   tentar raspar e avisar a cada run.
2. Rebaixar o WARNING repetido para um INFO único (ou nenhum log, se o estado
   já está registrado). O objetivo é parar o ruído diário sem esconder o fato.
3. Fazer quem depende dessa captura seguir sem ela, sem quebrar.
NÃO remova a feature do código inteiro: a plataforma pode voltar atrás, e
apagar o scraper perderia o trabalho todo."""


def demote_log_detail(*, evidence: str, occurrences: int, days: int) -> str:
    """Contexto de um job que conserta nível de log, não comportamento.

    O caso que motivou: ``campo='invite modal'`` gerou 711 WARNINGs em 15 dias
    — todos no **caminho de sucesso**. O LinkedIn passou a enviar convites sem
    abrir modal, e ``invitation_handler`` confirma o envio por
    ``pending_count()`` três linhas depois do aviso. O código funciona; o log
    mente.
    """
    return f"""Um WARNING está sendo emitido em caminho que NÃO é de erro:
{occurrences} ocorrências em {days} dias.

Evidência:
{evidence}

Confirme no código se o fluxo que emite esse aviso continua para um caminho de
sucesso logo depois. Se sim, a correção é o nível e o texto do log — não o
comportamento. O aviso deve sair só quando o fluxo realmente falhar.

Não altere a lógica de negócio. Se a condição de sucesso já é verificada
adiante, use essa mesma verificação para decidir se avisa."""


def build_commit_message(
    *, kind: str, subject: str, body: str, sig: str | None = None
) -> str:
    """Mensagem em Conventional Commits PT-BR, com a origem declarada.

    O rodapé diz que veio do evolve e qual assinatura de incidente originou —
    é o que permite, meses depois, entender por que aquela linha existe.
    """
    escopo = {
        "promote_selector": "selectors",
        "retire_feature": "evolve",
        "patch_bug": "fix",
        "demote_log": "log",
    }.get(kind, "evolve")
    tipo = "fix" if kind in {"patch_bug", "demote_log"} else "feat"
    if kind == "promote_selector":
        tipo = "fix"

    cabecalho = f"{tipo}({escopo}): {subject}"[:72]
    origem = f"\n\nIncidente: {sig}" if sig else ""
    return (
        f"{cabecalho}\n\n{body.strip()}{origem}\n\n"
        "Gerado automaticamente pelo evolve (autoevolução). "
        "Revise antes de mergear."
    )
