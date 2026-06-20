"""Generate authored LinkedIn posts via LLM.

Mirrors ``engagement_handler``: module-level validation helpers + a class
that builds the prompt and validates the output. Reuses
``load_resume_text``/``is_blacklisted`` so resume parsing and topic
blacklisting stay in one place.
"""

import re

from src.config.settings import logger
from src.core.ai.llm_provider import LLMProvider
from src.core.use_cases.engagement_handler import is_blacklisted

_MIN_CHARS = 80
_HARD_CAP_CHARS = 900
_PLACEHOLDER_RE = re.compile(
    r"\bTODO\b|\bFIXME\b|<\.\.\.>|<placeholder>", re.IGNORECASE
)
_HASHTAG_RE = re.compile(r"#\w+")

_FORMAT_GUIDE = {
    "snippet": "1 dica técnica em 3-5 linhas. Direto ao ponto, quase um código comentado em prosa.",
    "story": "situação → ação → lição, em no máximo 6 linhas. Tom de build-in-public.",
    "dissertativo": "tese + argumento curto + conclusão. Opinião técnica fundamentada.",
    "contrarian": "uma opinião polêmica (mas defensável) + reasoning + convite ao debate.",
}


def validate_draft(text: str) -> tuple[bool, str]:
    text = (text or "").strip().strip('"').strip("'")
    if not text:
        return False, "empty"
    if len(text) < _MIN_CHARS:
        return False, f"too short ({len(text)} chars)"
    if len(text) > _HARD_CAP_CHARS:
        return False, f"too long ({len(text)} chars)"
    if _PLACEHOLDER_RE.search(text):
        return False, "contains placeholder (TODO/FIXME/<...>)"
    if len(_HASHTAG_RE.findall(text)) > 5:
        return False, "too many hashtags"
    if is_blacklisted(text):
        return False, "blacklisted content"
    return True, text


class PostDrafter:
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

    def _build_prompt(self, topic: str, fmt: str, context: str) -> str:
        guide = _FORMAT_GUIDE.get(fmt, _FORMAT_GUIDE["dissertativo"])
        ctx_block = (
            f'\nMaterial de apoio:\n"""\n{context[:800]}\n"""\n' if context else ""
        )
        return (
            f"Você é {self.user_name}, {self.user_headline}.\n"
            f"Escreva um post autoral para o LinkedIn, em primeira pessoa.\n\n"
            f"Currículo (resumo, use para dar autenticidade):\n{self.resume[:500]}\n\n"
            f"Tema: {topic}\n"
            f"Formato: {fmt} — {guide}\n"
            f"{ctx_block}\n"
            f"Regras estritas:\n"
            f"- Curto e objetivo. Alvo 400-700 caracteres, MÁXIMO 900.\n"
            f"- Primeira linha = hook forte (contrarian, número, vulnerabilidade ou pergunta).\n"
            f"- Toda frase carrega peso. Zero filler.\n"
            f"- Quebras de linha frequentes (mobile-first).\n"
            f"- Encerre com uma pergunta ou CTA curto.\n"
            f"- 2-4 hashtags relevantes no fim.\n"
            f"- SEM emojis em excesso (no máximo 1).\n"
            f"- NÃO mencione que está procurando emprego.\n\n"
            f"Retorne APENAS o texto do post, sem preâmbulo, sem aspas.\n"
            f"Post:"
        )

    async def generate_draft(
        self, topic: str, fmt: str, context: str = "", retries: int = 1
    ) -> str | None:
        prompt = self._build_prompt(topic, fmt, context)
        for attempt in range(retries + 1):
            try:
                raw = await self.llm.complete(prompt)
            except Exception as e:
                logger.warning(f"generate_draft LLM call failed: {e}")
                return None
            # qwen3 e afins podem emitir <think>…</think> — remove.
            raw = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL).strip()
            ok, payload = validate_draft(raw)
            if ok:
                logger.info(f"Draft gerado ({len(payload)} chars, format={fmt})")
                return payload
            logger.info(
                f"Draft rejeitado ({payload}) tentativa {attempt + 1}/{retries + 1}"
            )
        return None
