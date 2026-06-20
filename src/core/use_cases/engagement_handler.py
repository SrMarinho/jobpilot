import os
import random
import re
from pathlib import Path

from src.config.settings import logger
from src.core.ai.llm_provider import LLMProvider


_BLACKLIST_KEYWORDS = {
    "politica",
    "política",
    "eleicao",
    "eleição",
    "religiao",
    "religião",
    "aborto",
    "vacina",
    "racismo",
    "lgbt",
    "bolsonaro",
    "lula",
    "trump",
    "biden",
    "abortion",
    "gun control",
    "vaccine",
    "election",
    "religion",
    "racist",
    "racism",
    "transgender",
    "vagas para",
    "estamos contratando",
    "we are hiring",
    "we're hiring",
    "estamos buscando",
    "recruiter",
    "recrutador",
}

_TECH_KEYWORDS = (
    "python",
    "node",
    "nodejs",
    "javascript",
    "typescript",
    "java",
    "golang",
    " go ",
    "rust",
    "react",
    "vue",
    "angular",
    "django",
    "flask",
    "fastapi",
    "spring",
    "kubernetes",
    "k8s",
    "docker",
    "devops",
    "cloud",
    "aws",
    "azure",
    "gcp",
    "google cloud",
    "terraform",
    "ci/cd",
    "cicd",
    "pipeline",
    "microservi",
    "api",
    "rest",
    "graphql",
    "sql",
    "postgres",
    "mysql",
    "mongodb",
    "redis",
    "banco de dados",
    "database",
    "backend",
    "frontend",
    "full-stack",
    "fullstack",
    "machine learning",
    "ml",
    " ia ",
    " ai ",
    "inteligência artificial",
    "inteligencia artificial",
    "llm",
    "data",
    "dados",
    "etl",
    "engenharia de software",
    "software",
    "desenvolv",
    "programa",
    "código",
    "codigo",
    "git",
    "linux",
    "observability",
    "monitoring",
    "rpa",
    "automacao",
    "automação",
    "agile",
    "scrum",
    "arquitetura",
    "architecture",
    "deploy",
    "infraestrutura",
    "infra",
    "engineer",
    "developer",
    "tech",
    "ti ",
    "framework",
    "biblioteca",
    "library",
)


def has_tech_keyword(text: str) -> bool:
    low = f" {text.lower()} "
    return any(kw in low for kw in _TECH_KEYWORDS)


_CLICHE_PATTERNS = (
    r"^(ótimo|otimo|excelente|incrível|incrivel|amazing|great|awesome) post[!.]?\s*$",
    r"^(concordo|i agree|agreed)[!.]?\s*$",
    r"^muito bom[!.]?\s*$",
    r"^perfect[oa]?[!.]?\s*$",
    r"^\W*$",
)
_CLICHE_RE = re.compile("|".join(_CLICHE_PATTERNS), re.IGNORECASE)


def load_resume_text(resume_path: str) -> str:
    p = Path(resume_path)
    if not p.exists():
        logger.warning(f"Resume not found at {resume_path}, using empty context")
        return ""
    if p.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(resume_path)
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    return p.read_text(encoding="utf-8", errors="ignore")


def is_blacklisted(text: str) -> bool:
    low = text.lower()
    return any(kw in low for kw in _BLACKLIST_KEYWORDS)


def is_cliche(comment: str) -> bool:
    return bool(_CLICHE_RE.match(comment.strip()))


# Linguagens/frameworks nomeados. Se o comentário cita um que NÃO aparece no
# post, o modelo alucinou o stack (ex: falar de Django num post sobre Spring).
_NAMED_TECH = (
    "python",
    "django",
    "flask",
    "fastapi",
    "java",
    "spring",
    "kotlin",
    "scala",
    "javascript",
    "typescript",
    "node",
    "nodejs",
    "react",
    "vue",
    "angular",
    "svelte",
    "golang",
    "rust",
    "c#",
    ".net",
    "php",
    "laravel",
    "symfony",
    "ruby",
    "rails",
    "elixir",
    "django rest",
    "express",
    "nestjs",
    "c++",
)


def foreign_tech_in_comment(comment: str, post_text: str) -> str | None:
    """Retorna o 1º termo de stack citado no comentário e ausente do post."""
    c = comment.lower()
    p = post_text.lower()
    for tech in _NAMED_TECH:
        # match por palavra p/ evitar substrings espúrias (ex: 'java' em 'javascript')
        pat = rf"(?<![a-z0-9]){re.escape(tech)}(?![a-z0-9])"
        if re.search(pat, c) and tech not in p:
            return tech
    return None


def validate_comment(comment: str) -> tuple[bool, str]:
    comment = (comment or "").strip().strip('"').strip("'")
    if not comment:
        return False, "empty"
    words = comment.split()
    if len(words) < 5:
        return False, f"too short ({len(words)} words)"
    if len(comment) > 200:
        return False, f"too long ({len(comment)} chars)"
    if is_cliche(comment):
        return False, "cliche"
    if "emoji" in comment.lower():
        return False, "mentions emoji"
    if re.search(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF]", comment):
        return False, "contains emoji"
    return True, comment


class EngagementHandler:
    def __init__(
        self,
        llm_provider: LLMProvider,
        resume_text: str,
        user_name: str = "",
        user_headline: str = "",
    ):
        self.llm = llm_provider
        self.resume = (resume_text or "")[:1500]
        self.user_name = user_name or "profissional de tecnologia"
        self.user_headline = (
            user_headline or "Software Engineer focado em Python e Node.js"
        )

    async def is_relevant(self, post_text: str) -> bool:
        if not post_text or len(post_text) < 20:
            return False
        if is_blacklisted(post_text):
            logger.debug("Post blacklisted by keyword filter")
            return False
        if os.getenv("ENGAGE_SKIP_RELEVANCE") == "1":
            logger.info("ENGAGE_SKIP_RELEVANCE=1, assuming relevant")
            return True
        # Keyword heuristic first — robust against weak local LLMs that
        # over-reject. Tech keyword present => relevant, skip LLM.
        if has_tech_keyword(post_text):
            logger.info("is_relevant: tech keyword match, relevant (skipped LLM)")
            return True
        prompt = (
            f"Voce avalia se um post do LinkedIn fala sobre tecnologia/desenvolvimento de software.\n\n"
            f'Post:\n"""\n{post_text[:600]}\n"""\n\n'
            f"O post menciona tecnologia, programacao, desenvolvimento, devops, cloud, dados, IA, "
            f"engenharia de software, ferramentas tech, carreira em TI, ou conteudo similar?\n"
            f"Em duvida, responda 'sim'. So responda 'nao' se for claramente nao-tecnico "
            f"(politica, religiao, fofoca, motivacional generico sem tech).\n"
            f"Responda APENAS uma palavra: sim OU nao."
        )
        try:
            resp = (await self.llm.complete(prompt)).strip().lower()
        except Exception as e:
            logger.warning(f"is_relevant LLM call failed: {e}")
            return False
        result = resp.startswith("sim") or resp.startswith("yes")
        logger.info(
            f"is_relevant verdict: {result} (resp={resp[:60]!r}, "
            f"text_len={len(post_text)})"
        )
        return result

    # Variantes A/B: dois ângulos de comentário. O variant usado é gravado no
    # tracker p/ o relatório cruzar qual estilo aparece mais (conversão real
    # depende de tracking de respostas — futuro).
    _VARIANTS = {
        "insight": "Traga 1 insight técnico concreto ou uma observação que agregue.",
        "pergunta": "Faça 1 pergunta específica e relevante que convide ao diálogo.",
    }

    def _pick_variant(self) -> str:
        return random.choice(list(self._VARIANTS.keys()))

    async def generate_comment(
        self, post_text: str, author: str, variant: str | None = None
    ) -> tuple[str | None, str]:
        """Gera comentário. Retorna ``(texto|None, variant)``."""
        variant = variant or self._pick_variant()
        angle = self._VARIANTS.get(variant, self._VARIANTS["insight"])
        prompt = (
            f"Leia o post do LinkedIn abaixo e escreva 1 comentário como peer profissional.\n\n"
            f'Post de {author}:\n"""\n{post_text[:800]}\n"""\n\n'
            f"Tarefa: comentário curto (5-15 palavras), profissional, no mesmo idioma do post.\n"
            f"Ângulo desta vez: {angle}\n\n"
            f"ANCORAGEM (essencial):\n"
            f"- Comente APENAS sobre o que o post realmente diz. Use os termos, a "
            f"tecnologia e o stack que o PRÓPRIO post menciona.\n"
            f"- NUNCA introduza linguagens, frameworks ou ferramentas que o post não "
            f"cita. Se o post fala de Java/Spring, não fale de Python/Django.\n"
            f"- Não traga seu próprio stack pessoal para o comentário.\n\n"
            f"Regras estritas:\n"
            f"- NÃO use emojis\n"
            f"- NÃO mencione que está procurando emprego\n"
            f"- NÃO use clichês ('ótimo post!', 'concordo plenamente', 'muito bom!')\n"
            f"- NÃO seja sycophantic\n"
            f"- Se não tiver algo de valor e ancorado a dizer, retorne string vazia\n\n"
            f"Retorne APENAS o comentário, sem aspas, sem preâmbulo.\n"
            f"Comentário:"
        )
        for attempt in range(2):  # 1 tentativa + 1 retry
            try:
                raw = await self.llm.complete(prompt)
            except Exception as e:
                logger.warning(f"generate_comment LLM call failed: {e}")
                return None, variant
            ok, payload = validate_comment(raw)
            if not ok:
                logger.info(
                    f"Comment rejected ({payload}) tentativa {attempt + 1}: {raw!r}"
                )
                continue
            if is_blacklisted(payload):
                logger.info("Comment rejected (blacklisted content)")
                continue
            foreign = foreign_tech_in_comment(payload, post_text)
            if foreign:
                logger.info(
                    f"Comment rejected (stack alucinado: {foreign!r} ausente do post) "
                    f"tentativa {attempt + 1}: {payload!r}"
                )
                continue
            return payload, variant
        return None, variant
