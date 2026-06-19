import os
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

    async def generate_comment(self, post_text: str, author: str) -> str | None:
        prompt = (
            f"Você é {self.user_name}, {self.user_headline}.\n"
            f"Você está engajando em um post do LinkedIn como peer profissional.\n\n"
            f"Currículo (resumo):\n{self.resume[:500]}\n\n"
            f'Post de {author}:\n"""\n{post_text[:800]}\n"""\n\n'
            f"Escreva 1 comentário curto (5-15 palavras), profissional, no mesmo idioma do post.\n"
            f"Pode trazer um insight técnico, agradecimento concreto, ou pergunta relevante.\n\n"
            f"Regras estritas:\n"
            f"- NÃO use emojis\n"
            f"- NÃO mencione que está procurando emprego\n"
            f"- NÃO use clichês ('ótimo post!', 'concordo plenamente', 'muito bom!')\n"
            f"- NÃO seja sycophantic\n"
            f"- Se não tiver algo de valor a dizer, retorne string vazia\n\n"
            f"Retorne APENAS o comentário, sem aspas, sem preâmbulo.\n"
            f"Comentário:"
        )
        try:
            raw = await self.llm.complete(prompt)
        except Exception as e:
            logger.warning(f"generate_comment LLM call failed: {e}")
            return None
        ok, payload = validate_comment(raw)
        if not ok:
            logger.info(f"Comment rejected ({payload}): {raw!r}")
            return None
        if is_blacklisted(payload):
            logger.info("Comment rejected (blacklisted content)")
            return None
        return payload
