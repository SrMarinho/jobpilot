"""Gera o DM curto de follow-up pós-conexão via LLM.

Mensagem de 1-2 linhas: agradece a conexão + 1 gancho relevante ligado ao
headline da pessoa. Sem pitch de emprego, sem clichê. Reusa o filtro de
blacklist do engagement_handler.
"""

import re

from src.config.settings import logger
from src.core.ai.llm_provider import LLMProvider
from src.core.use_cases.engagement_handler import is_blacklisted

_MIN_CHARS = 30
_MAX_CHARS = 320
_CLICHE_RE = re.compile(
    r"^(obrigado pela conexão|thanks for connecting|valeu pela conexão)[!.]?\s*$",
    re.IGNORECASE,
)


def validate_dm(text: str) -> tuple[bool, str]:
    text = (text or "").strip().strip('"').strip("'")
    if not text:
        return False, "empty"
    if len(text) < _MIN_CHARS:
        return False, f"too short ({len(text)} chars)"
    if len(text) > _MAX_CHARS:
        return False, f"too long ({len(text)} chars)"
    if _CLICHE_RE.match(text):
        return False, "cliche"
    if is_blacklisted(text):
        return False, "blacklisted content"
    return True, text


class FollowupDMGenerator:
    def __init__(
        self,
        llm_provider: LLMProvider,
        resume_text: str = "",
        user_name: str = "",
        user_headline: str = "",
    ):
        self.llm = llm_provider
        self.resume = (resume_text or "")[:1000]
        self.user_name = user_name or "profissional de tecnologia"
        self.user_headline = (
            user_headline or "Software Engineer focado em Python e Node.js"
        )

    def _build_prompt(self, name: str, headline: str) -> str:
        first = (name or "").split()[0] if name else ""
        hl = f"\nHeadline dela(e): {headline}" if headline else ""
        return (
            f"Você é {self.user_name}, {self.user_headline}.\n"
            f"Acabou de se conectar com {first or 'uma pessoa'} no LinkedIn.{hl}\n\n"
            f"Escreva uma mensagem curta (1-2 frases, máx 280 caracteres) "
            f"agradecendo a conexão e puxando um gancho genuíno relacionado à "
            f"área dela(e). Tom de peer profissional, primeira pessoa.\n\n"
            f"Regras estritas:\n"
            f"- NÃO use emojis\n"
            f"- NÃO peça emprego, indicação ou favor\n"
            f"- NÃO use clichê seco ('obrigado pela conexão!')\n"
            f"- Se não souber o que dizer de relevante, faça uma pergunta leve "
            f"sobre a área dela(e)\n\n"
            f"Retorne APENAS a mensagem, sem aspas, sem preâmbulo.\n"
            f"Mensagem:"
        )

    async def generate(
        self, name: str, headline: str = "", retries: int = 1
    ) -> str | None:
        prompt = self._build_prompt(name, headline)
        for attempt in range(retries + 1):
            try:
                raw = await self.llm.complete(prompt)
            except Exception as e:
                logger.warning(f"followup DM LLM call failed: {e}")
                return None
            raw = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL).strip()
            ok, payload = validate_dm(raw)
            if ok:
                logger.info(f"Follow-up DM gerado ({len(payload)} chars) p/ {name!r}")
                return payload
            logger.info(
                f"DM rejeitado ({payload}) tentativa {attempt + 1}/{retries + 1}"
            )
        return None
