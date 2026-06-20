"""Content sources for autopost drafts.

Each source returns ``(topic, context)``: a short subject line plus optional
raw material the LLM should lean on (git subjects, an RSS item, …). The
weekday helpers decide the default source/format for scheduled runs.
"""

import random
import subprocess
from datetime import date

from src.config.settings import logger

FORMATS = ("snippet", "story", "dissertativo", "contrarian")

# Pool used by the ``template`` source — evergreen tech themes aligned with a
# backend/Python/Node profile. Kept short and opinionated on purpose.
_TOPICS = (
    "por que observabilidade importa mais que testes em produção",
    "o custo escondido de microsserviços prematuros",
    "Python async: quando ajuda e quando atrapalha",
    "idempotência em retries: o detalhe que evita cobrança dupla",
    "lição de um bug de race condition que custou caro",
    "ETL não é glamouroso, mas é onde o valor vaza",
    "por que eu prefiro logs estruturados a debugger",
    "feature flags como ferramenta de coragem, não de medo",
    "o que aprendi automatizando tarefas repetitivas com RPA",
    "índices de banco: o ganho de performance mais barato que existe",
    "code review é sobre contexto, não sobre estilo",
    "deploy na sexta: o problema nunca foi o dia",
)


def default_format_for_today() -> str:
    return FORMATS[date.today().weekday() % len(FORMATS)]


def default_source_for_today() -> str:
    wd = date.today().weekday()  # 0=segunda
    if wd == 1:  # terça → build-in-public dos commits
        return "commit"
    if wd == 4:  # sexta → conteúdo a partir de RSS
        return "rss"
    return "template"


def _commit_context() -> tuple[str, str]:
    try:
        out = subprocess.run(
            ["git", "log", "--since=1 week ago", "--pretty=%s"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        subjects = [s.strip() for s in out.stdout.splitlines() if s.strip()]
    except Exception as e:
        logger.warning(f"commit source git log failed: {e}")
        subjects = []
    if not subjects:
        return _template_context()
    context = "\n".join(f"- {s}" for s in subjects[:15])
    return "o que construí essa semana (build-in-public)", context


def _rss_context() -> tuple[str, str]:
    try:
        import feedparser  # optional dep
    except Exception:
        logger.warning("feedparser não instalado, caindo para template")
        return _template_context()
    feeds = (
        "https://hnrss.org/frontpage",
        "https://dev.to/feed",
    )
    for url in feeds:
        try:
            parsed = feedparser.parse(url)
            if parsed.entries:
                entry = parsed.entries[0]
                title = getattr(entry, "title", "").strip()
                summary = getattr(entry, "summary", "").strip()
                if title:
                    return title, f"{title}\n\n{summary[:600]}"
        except Exception as e:
            logger.debug(f"RSS feed {url} failed: {e}")
            continue
    return _template_context()


def _template_context() -> tuple[str, str]:
    return random.choice(_TOPICS), ""


def pick_content(source: str, topic: str | None = None) -> tuple[str, str]:
    """Resolve a source into ``(topic, context)`` for the drafter."""
    if source == "manual":
        if not topic:
            raise ValueError("source=manual exige --topic")
        return topic, ""
    if source == "commit":
        return _commit_context()
    if source == "rss":
        return _rss_context()
    # template (default)
    if topic:
        return topic, ""
    return _template_context()
