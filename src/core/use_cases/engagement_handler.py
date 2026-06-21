import os
import random
import re

from src.config.settings import logger
from src.core.ai.llm_provider import LLMProvider
from src.core.use_cases.content_filters import (
    comment_is_grounded,
    foreign_tech_in_comment,
    has_tech_keyword,
    is_blacklisted,
    is_commentable_post,
    is_trivial,
    validate_comment,
)


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
        # Post fino/só-link/só-imagem: sem substância real p/ ancorar comentário.
        # Comentar aqui força o modelo a inventar (ex: 'RPA em produção').
        if not is_commentable_post(post_text):
            logger.info("is_relevant: post sem substância (link/imagem), pulando")
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

    # Hashtags do post (#dataeng, #python). Sinalizam o tema/contexto que o
    # autor escolheu — ajudam o modelo a ancorar melhor o comentário.
    @staticmethod
    def _extract_tags(post_text: str, limit: int = 8) -> list[str]:
        tags = re.findall(r"#(\w[\w-]{1,30})", post_text or "")
        seen: list[str] = []
        for t in tags:
            if t.lower() not in {x.lower() for x in seen}:
                seen.append(t)
            if len(seen) >= limit:
                break
        return seen

    async def generate_comment(
        self, post_text: str, author: str, variant: str | None = None
    ) -> tuple[str | None, str]:
        """Gera comentário. Retorna ``(texto|None, variant)``."""
        variant = variant or self._pick_variant()
        angle = self._VARIANTS.get(variant, self._VARIANTS["insight"])
        tags = self._extract_tags(post_text)
        tags_line = (
            f"Tags do post (tema sinalizado pelo autor): {', '.join('#' + t for t in tags)}\n"
            f"Use as tags só como contexto do tema; NÃO copie a tag literal no comentário "
            f"nem trate tag como fato técnico do projeto.\n\n"
            if tags
            else ""
        )
        prompt = (
            f"Leia o post do LinkedIn abaixo e escreva 1 comentário como peer profissional.\n\n"
            f'Post de {author}:\n"""\n{post_text[:800]}\n"""\n\n'
            f"{tags_line}"
            f"Tarefa: comentário curto (5-15 palavras), profissional, no mesmo idioma do post.\n"
            f"Ângulo desta vez: {angle}\n\n"
            f"ANCORAGEM (essencial):\n"
            f"- Comente APENAS sobre o que o post realmente diz. Use os termos, a "
            f"tecnologia e o stack que o PRÓPRIO post menciona.\n"
            f"- NUNCA introduza linguagens, frameworks ou ferramentas que o post não "
            f"cita. Se o post fala de Java/Spring, não fale de Python/Django.\n"
            f"- Não traga seu próprio stack pessoal para o comentário.\n"
            f"- NÃO invente fatos sobre o projeto (ex: que está 'em produção', que usa "
            f"'RPA', 'microsserviços', que 'escalou', resultados ou métricas) se o post "
            f"não disser isso explicitamente.\n"
            f"- Se o post só compartilha um link ou imagem sem descrever conteúdo "
            f"técnico no texto, retorne string vazia (você não vê o link/imagem).\n\n"
            f"Regras estritas:\n"
            f"- NÃO use emojis\n"
            f"- NÃO mencione que está procurando emprego\n"
            f"- NÃO use clichês ('ótimo post!', 'concordo plenamente', 'muito bom!')\n"
            f"- NÃO seja sycophantic\n"
            f"- NÃO faça perguntas de iniciante nem explique o básico (ex: 'o que é "
            f"uma API?', 'como o JSON facilita a comunicação?', 'para que serve "
            f"Docker?'). Comente como SÊNIOR: traga nuance, trade-off, experiência "
            f"prática ou uma pergunta técnica não-óbvia.\n"
            f"- Se só tiver algo trivial/óbvio a dizer, retorne string vazia\n"
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
            if not comment_is_grounded(payload, post_text):
                logger.info(
                    f"Comment rejected (ungrounded: nada em comum com o post) "
                    f"tentativa {attempt + 1}: {payload!r}"
                )
                continue
            if is_trivial(payload):
                logger.info(
                    f"Comment rejected (trivial/iniciante) "
                    f"tentativa {attempt + 1}: {payload!r}"
                )
                continue
            return payload, variant
        return None, variant
