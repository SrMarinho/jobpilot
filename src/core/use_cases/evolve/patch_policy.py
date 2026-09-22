"""O que um patch automático pode tocar, e quanto pode custar.

Este é o módulo que decide se um LLM com permissão de escrita no repositório é
uma boa ideia ou um acidente. Ele é puro e é o mais testado do conjunto de
propósito: as travas aqui não podem depender de o prompt ter sido bem escrito
nem de o modelo ter colaborado.

Três princípios:

**Denylist vence allowlist, sempre.** Um caminho negado não entra por estar
também permitido. Na dúvida, nega.

**A verificação de caminhos roda ANTES de qualquer execução.** ``pytest``
importa o código do patch — ou seja, executa código escrito por LLM. Conferir
os caminhos depois de rodar os testes seria conferir depois de já ter
executado.

**O evolve está na própria denylist.** O sistema não pode patchear os seus
guard rails. E como a denylist mora dentro de ``evolve/``, ela se protege.

O que não pode ser tocado, e por quê:

- ``.env*`` — segredos e a URL do Postgres de produção.
- ``.local/**`` — sessão do Chrome, JSONs de estado e os XMLs do Agendador. Um
  patch em task agendada ou não faz nada (precisa de re-import como admin) ou
  derruba todas as tasks em silêncio.
- ``src/core/persistence/**`` — é o caminho até o banco de produção.
- ``src/core/use_cases/evolve/**`` e ``src/automation/evolve/**`` — os guard
  rails.
- ``.github/**`` — o CI é o segundo par de olhos independente.
- ``pyproject.toml``/``uv.lock`` — dependência nova é decisão humana.
- ``main.py``, ``router.py``, ``src/config/**``, ``telegram.py`` — a fiação por
  onde tudo passa, incluindo o canal por onde o dono é avisado.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass

# Padrões no formato do fnmatch, contra o caminho relativo com "/" (como o
# `git status --porcelain` devolve).
ALLOW = (
    "src/automation/pages/*.py",
    "src/core/use_cases/*.py",
    "src/core/use_cases/apply/*.py",
    "src/core/use_cases/report/*.py",
    "src/automation/tasks/*.py",
    "tests/*.py",
    "tests/fixtures/*",
    "tests/fixtures/**/*",
    "docs/*.md",
)

DENY = (
    ".env",
    ".env.*",
    "*.env",
    ".local/*",
    ".local/**/*",
    ".github/*",
    ".github/**/*",
    "src/config/*",
    "src/config/**/*",
    "src/core/persistence/*",
    "src/core/persistence/**/*",
    "src/core/use_cases/evolve/*",
    "src/core/use_cases/evolve/**/*",
    "src/automation/evolve/*",
    "src/automation/evolve/**/*",
    "src/utils/telegram.py",
    "src/bot/*",
    "src/bot/**/*",
    "main.py",
    "src/interfaces/cli/router.py",
    "pyproject.toml",
    "uv.lock",
    ".pre-commit-config.yaml",
    ".gitignore",
    "CLAUDE.md",
    "*.ps1",
    "*.bat",
    "*.vbs",
    "*.xml",
    "*.yml",
    "*.yaml",
)

#: Um patch de selector mexe em uma constante e num teste. Diff maior que isso
#: não é a correção que pedimos — é o modelo tendo ideias.
MAX_FILES = 4
MAX_DIFF_LINES = 120

#: Tetos de gasto. O patch usa `claude -p`, que cobra por token.
MAX_PATCHES_PER_DAY = 2
MAX_PATCHES_PER_WEEK = 5
DAILY_USD_CAP = 1.0

#: Falhas de gate consecutivas (entre jobs diferentes) que abrem o cooldown.
#: Sinal de que algo sistêmico quebrou — não de que este job é ruim.
GLOBAL_FAILURE_THRESHOLD = 3
COOLDOWN_HOURS = 24

#: Branches `evolve/*` abertas ao mesmo tempo. Sem teto, um campo que quebra
#: toda semana acumula branches que ninguém revisa.
MAX_OPEN_BRANCHES = 3

BRANCH_PREFIX = "evolve/"
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _normalize(path: str) -> str:
    """Caminho relativo com "/", sem o prefixo "./".

    Cuidado que já custou um bug: ``lstrip("./")`` remove **todos** os
    caracteres do conjunto, então ``.env`` virava ``env`` e escapava da
    denylist — ficava negado apenas pelo fallback da allowlist, e bastaria uma
    allowlist mais ampla pra ``.env`` passar. Remoção de prefixo é
    ``removeprefix``, não ``lstrip``.
    """
    normalized = path.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized.removeprefix("./")
    return normalized


def _matches(path: str, patterns: tuple[str, ...]) -> str:
    """Primeiro padrão que casa, ou string vazia."""
    normalized = _normalize(path)
    for pattern in patterns:
        if fnmatch.fnmatch(normalized, pattern):
            return pattern
    return ""


@dataclass(frozen=True, slots=True)
class PathVerdict:
    path: str
    allowed: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.allowed


def check_path(path: str) -> PathVerdict:
    """Um caminho pode ser tocado por patch automático?"""
    if not path or not path.strip():
        return PathVerdict(path, False, "caminho vazio")

    normalized = _normalize(path)
    if ".." in normalized.split("/"):
        # Um patch que sobe de diretório está saindo do repositório.
        return PathVerdict(path, False, "caminho sai do repositório (..)")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        return PathVerdict(path, False, "caminho absoluto")

    denied = _matches(normalized, DENY)
    if denied:
        # Denylist vence: nega mesmo que também esteja na allowlist.
        return PathVerdict(path, False, f"proibido por política ({denied})")

    allowed = _matches(normalized, ALLOW)
    if not allowed:
        return PathVerdict(path, False, "fora da allowlist")

    return PathVerdict(path, True)


@dataclass(frozen=True, slots=True)
class DiffVerdict:
    allowed: bool
    reason: str = ""
    rejected: tuple[PathVerdict, ...] = ()

    def __bool__(self) -> bool:
        return self.allowed


def check_diff(paths: list[str], *, changed_lines: int = 0) -> DiffVerdict:
    """O conjunto de arquivos mexidos pelo patch é aceitável?"""
    if not paths:
        return DiffVerdict(False, "o patch não mudou arquivo nenhum")

    reprovados = tuple(v for v in (check_path(p) for p in paths) if not v)
    if reprovados:
        nomes = ", ".join(f"{v.path} ({v.reason})" for v in reprovados)
        return DiffVerdict(False, f"caminho proibido: {nomes}", reprovados)

    if len(paths) > MAX_FILES:
        return DiffVerdict(False, f"{len(paths)} arquivos mexidos (máximo {MAX_FILES})")
    if changed_lines > MAX_DIFF_LINES:
        return DiffVerdict(
            False, f"{changed_lines} linhas alteradas (máximo {MAX_DIFF_LINES})"
        )
    return DiffVerdict(True)


def slug(text: str, *, limit: int = 32) -> str:
    """Trecho seguro para nome de branch."""
    limpo = _SLUG_RE.sub("-", text.lower()).strip("-")
    return (limpo[:limit].rstrip("-")) or "job"


def branch_name(kind: str, subject: str, *, day: str) -> str:
    """``evolve/<kind>-<assunto>-<AAAAMMDD>``.

    O prefixo não é decoração: o push confere que a branch começa com
    ``evolve/`` antes de acontecer.
    """
    return f"{BRANCH_PREFIX}{slug(kind, limit=20)}-{slug(subject)}-{day}"


def is_pushable(branch: str) -> bool:
    """Só branch de evolução pode ser empurrada por código automático.

    A garantia de verdade contra push em master é branch protection no
    GitHub — esta checagem é a de dentro, e não substitui a de fora.
    """
    return branch.startswith(BRANCH_PREFIX) and len(branch) > len(BRANCH_PREFIX)


@dataclass(frozen=True, slots=True)
class BudgetVerdict:
    allowed: bool
    reason: str = ""

    def __bool__(self) -> bool:
        return self.allowed


def check_budget(
    *,
    patches_today: int,
    patches_week: int,
    usd_today: float,
    open_branches: int,
    paused: bool = False,
    in_cooldown: bool = False,
    enabled: bool = True,
) -> BudgetVerdict:
    """Pode gastar mais um patch agora?

    A ordem é a dos kill switches primeiro: quem desligou o sistema não quer
    saber de contagem.
    """
    if not enabled:
        return BudgetVerdict(False, "evolve desligado (EVOLVE_ENABLED)")
    if paused:
        return BudgetVerdict(False, "evolve pausado (config evolve pause)")
    if in_cooldown:
        return BudgetVerdict(
            False, f"em cooldown após {GLOBAL_FAILURE_THRESHOLD} falhas seguidas"
        )
    if patches_today >= MAX_PATCHES_PER_DAY:
        return BudgetVerdict(
            False, f"teto diário de patches ({patches_today}/{MAX_PATCHES_PER_DAY})"
        )
    if patches_week >= MAX_PATCHES_PER_WEEK:
        return BudgetVerdict(
            False, f"teto semanal de patches ({patches_week}/{MAX_PATCHES_PER_WEEK})"
        )
    if usd_today >= DAILY_USD_CAP:
        return BudgetVerdict(
            False, f"teto diário de custo (US$ {usd_today:.2f}/{DAILY_USD_CAP:.2f})"
        )
    if open_branches >= MAX_OPEN_BRANCHES:
        return BudgetVerdict(
            False,
            f"{open_branches} branches evolve/* abertas "
            f"(máximo {MAX_OPEN_BRANCHES}) — revise as pendentes",
        )
    return BudgetVerdict(True)


#: Ferramentas que o `claude -p` recebe. Bash de fora é o que garante que ele
#: não roda git, não instala dependência e não sai pra rede — todo git é feito
#: pelo nosso Python, com argv fixo.
ALLOWED_TOOLS = ("Read", "Edit", "Write", "Grep", "Glob")
DISALLOWED_TOOLS = ("Bash", "WebFetch", "WebSearch", "Task", "NotebookEdit")

#: Variáveis que NÃO são repassadas ao processo do agente.
BLOCKED_ENV = (
    "DATABASE_URL",
    "TELEGRAM_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_ADMIN_ID",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
)


def child_env(environ: dict[str, str]) -> dict[str, str]:
    """Ambiente do agente: o ambiente atual menos os segredos.

    ``DATABASE_URL`` vazio (e não ausente) é deliberado: é o que faz a
    persistência cair no modo JSON local, então um teste que instancie tracker
    durante os gates não escreve no Postgres de produção.
    """
    out = {k: v for k, v in environ.items() if k not in BLOCKED_ENV}
    out["DATABASE_URL"] = ""
    return out
