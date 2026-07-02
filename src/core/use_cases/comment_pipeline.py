"""Pipeline multi-modelo p/ comentário de engage.

Fluxo: Sonnet GERA → Fable REVISA (pontos objetivos de melhoria) → Sonnet
REGERA aplicando os pontos → contagem de palavras em Python → se estourou,
Haiku COMPRIME para caber no limite. Motivação: o modelo local (qwen3:8b) não
sabe contar palavras — comentários bons eram rejeitados por "too long" e o
engage passava dias sem comentar. Contar aqui (determinístico) e delegar a
compressão a um modelo barato resolve sem afrouxar o limite.

Cada estágio é best-effort: falha de um estágio degrada para o texto anterior
em vez de abortar (o validate final do handler continua sendo o gate).
"""

import os

from src.config.settings import logger
from src.core.ai.llm_provider import ClaudeProvider, LLMProvider

_GENERATOR_MODEL = os.getenv("ENGAGE_GENERATOR_MODEL", "claude-sonnet-5")
_REVIEWER_MODEL = os.getenv("ENGAGE_REVIEWER_MODEL", "claude-fable-5")
_COMPRESSOR_MODEL = os.getenv("ENGAGE_COMPRESSOR_MODEL", "claude-haiku-4-5-20251001")


def count_words(text: str) -> int:
    return len((text or "").split())


class CommentPipeline:
    """Gera comentário via Sonnet + revisão Fable + compressão Haiku."""

    def __init__(
        self,
        generator: LLMProvider | None = None,
        reviewer: LLMProvider | None = None,
        compressor: LLMProvider | None = None,
    ):
        self.generator = generator or ClaudeProvider(model=_GENERATOR_MODEL)
        self.reviewer = reviewer or ClaudeProvider(model=_REVIEWER_MODEL)
        self.compressor = compressor or ClaudeProvider(model=_COMPRESSOR_MODEL)

    async def _review(
        self, post_text: str, draft: str, min_words: int, max_words: int
    ) -> str | None:
        """Fable avalia o rascunho. Retorna ``None`` se aprovado, senão os
        pontos de melhoria (texto curto, 1 linha por ponto)."""
        prompt = (
            "Você é um revisor sênior de comentários do LinkedIn.\n\n"
            f'Post original:\n"""\n{post_text[:800]}\n"""\n\n'
            f'Comentário candidato:\n"""\n{draft}\n"""\n\n'
            "Avalie objetivamente:\n"
            "1. Responde diretamente ao que o post diz/pergunta?\n"
            "2. Tom sênior: mecanismo, trade-off ou experiência concreta — sem "
            "clichê, sem entusiasmo vazio, sem pergunta de iniciante?\n"
            "3. Ancorado SÓ no que o post diz (sem stack/fatos inventados)?\n"
            f"4. Está entre {min_words} e {max_words} palavras?\n\n"
            "Se está bom em todos os pontos, responda exatamente: OK\n"
            "Senão, liste até 3 pontos de melhoria objetivos e acionáveis "
            "(1 linha cada). NÃO reescreva o comentário; só os pontos."
        )
        try:
            resp = (await self.reviewer.complete(prompt)).strip()
        except Exception as e:
            logger.warning(f"CommentPipeline review falhou (segue sem revisão): {e}")
            return None
        if not resp or resp.strip().upper().startswith("OK"):
            return None
        return resp[:600]

    async def _regenerate(
        self, base_prompt: str, draft: str, review_points: str
    ) -> str | None:
        prompt = (
            f"{base_prompt}\n\n"
            f'Seu rascunho anterior:\n"""\n{draft}\n"""\n\n'
            f"Um revisor sênior apontou estes pontos de melhoria:\n{review_points}\n\n"
            "Reescreva o comentário aplicando os pontos. Mantenha o mesmo idioma "
            "do post e retorne APENAS o comentário final."
        )
        try:
            return (await self.generator.complete(prompt)).strip()
        except Exception as e:
            logger.warning(f"CommentPipeline regen falhou (mantém rascunho): {e}")
            return None

    async def _compress(self, text: str, max_words: int, post_text: str) -> str | None:
        prompt = (
            f"Reescreva o comentário de LinkedIn abaixo em NO MÁXIMO {max_words} "
            "palavras. Mantenha o mesmo idioma, a substância técnica e o tom "
            "sênior. Corte o menos essencial; NÃO adicione nada novo, NÃO use "
            "emojis.\n\n"
            f'Contexto (post comentado):\n"""\n{post_text[:400]}\n"""\n\n'
            f'Comentário ({count_words(text)} palavras):\n"""\n{text}\n"""\n\n'
            "Retorne APENAS o comentário reescrito, sem aspas nem preâmbulo."
        )
        try:
            return (await self.compressor.complete(prompt)).strip().strip('"')
        except Exception as e:
            logger.warning(f"CommentPipeline compress falhou: {e}")
            return None

    async def generate(
        self,
        base_prompt: str,
        post_text: str,
        min_words: int,
        max_words: int,
    ) -> str | None:
        """Roda o pipeline completo. Retorna o texto final (ainda passa pelos
        filtros/validate do chamador) ou ``None`` se nada utilizável."""
        try:
            draft = (await self.generator.complete(base_prompt)).strip()
        except Exception as e:
            logger.warning(f"CommentPipeline generate falhou: {e}")
            return None
        if not draft:
            return None

        review_points = await self._review(post_text, draft, min_words, max_words)
        if review_points:
            logger.info(f"CommentPipeline: revisor apontou → {review_points!r}")
            regen = await self._regenerate(base_prompt, draft, review_points)
            if regen:
                draft = regen

        # Contagem determinística em Python — modelo não conta palavras.
        for _ in range(2):
            if count_words(draft) <= max_words:
                break
            logger.info(
                f"CommentPipeline: {count_words(draft)} palavras > {max_words}, "
                "comprimindo via Haiku"
            )
            compressed = await self._compress(draft, max_words, post_text)
            if not compressed:
                break
            draft = compressed

        if count_words(draft) > max_words:
            logger.info(
                f"CommentPipeline: ainda {count_words(draft)} palavras após "
                "compressão — descartando"
            )
            return None
        return draft
