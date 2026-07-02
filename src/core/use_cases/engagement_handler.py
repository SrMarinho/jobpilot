import os
import random
import re

from src.config.settings import logger
from src.core.ai.llm_provider import LLMProvider
from src.core.use_cases.comment_pipeline import CommentPipeline
from src.core.use_cases.comment_filters import (
    comment_is_grounded,
    foreign_tech_in_comment,
    is_junior_tone,
    is_refusal,
    is_trivial,
    validate_comment,
)
from src.core.use_cases.content_filters import (
    has_tech_keyword,
    is_blacklisted,
    is_commentable_post,
    post_asks_question,
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
        # Pipeline multi-modelo (Sonnet gera → Fable revisa → Haiku comprime).
        # ENGAGE_CLAUDE_PIPELINE=0 desliga e volta ao provider único (self.llm).
        self.pipeline: CommentPipeline | None = (
            CommentPipeline()
            if os.getenv("ENGAGE_CLAUDE_PIPELINE", "1") == "1"
            else None
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

    # Variantes A/B: ângulos de comentário, cada um com seu tamanho-alvo. O
    # variant usado é gravado no tracker p/ o relatório cruzar qual estilo
    # aparece mais (conversão real depende de tracking de respostas — futuro).
    _VARIANTS = {
        "insight": {
            "angle": "Traga 1 insight técnico concreto ou uma observação que agregue.",
            "min_words": 5,
            "max_words": 15,
        },
        "tecnico": {
            "angle": (
                "Faça um diagnóstico técnico e traga o COMO: mecanismo, config, "
                "padrão ou trade-off concreto — não só o QUE. Densidade de quem já "
                "levou isso para produção."
            ),
            "min_words": 15,
            "max_words": 30,
        },
        "pergunta": {
            "angle": (
                "Faça 1 pergunta específica e não-óbvia que convide ao diálogo — "
                "nível sênior, sobre trade-off/operação/edge-case real do post."
            ),
            "min_words": 8,
            "max_words": 18,
        },
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

    def _build_prompt(
        self,
        post_text: str,
        author: str,
        angle: str,
        min_words: int,
        max_words: int,
    ) -> str:
        tags = self._extract_tags(post_text)
        tags_line = (
            f"Tags do post (tema sinalizado pelo autor): {', '.join('#' + t for t in tags)}\n"
            f"Use as tags só como contexto do tema; NÃO copie a tag literal no comentário "
            f"nem trate tag como fato técnico do projeto.\n\n"
            if tags
            else ""
        )
        question_block = (
            "O post FAZ uma pergunta — ela é o seu gancho. Responda-a "
            "DIRETAMENTE na primeira frase, com experiência concreta (situação "
            "real + o que aconteceu), e então adicione 1 nuance/trade-off. NÃO "
            "responda com outra pergunta genérica.\n\n"
            if post_asks_question(post_text)
            else ""
        )
        return (
            f"Leia o post do LinkedIn abaixo e escreva 1 comentário como peer profissional.\n\n"
            f'Post de {author}:\n"""\n{post_text[:800]}\n"""\n\n'
            f"{tags_line}"
            f"Você é {self.user_headline}, engenheiro experiente. Escreva com a "
            f"densidade de quem já levou isso para produção — mecanismo, trade-off "
            f"ou número, não entusiasmo.\n\n"
            f"LIMITE DURO DE TAMANHO: entre {min_words} e {max_words} palavras. "
            f"Antes de responder, CONTE as palavras do comentário; se passar de "
            f"{max_words}, corte o menos essencial até caber. Comentário longo "
            f"será descartado.\n"
            f"Ângulo desta vez: {angle}\n\n"
            f"{question_block}"
            f"EXEMPLOS:\n"
            f"- BOM: 'Uso pra fan-out de I/O independente; o que mais pega é "
            f"context propagation — MDC some ao trocar de thread. Resolvi com "
            f"taskDecorator copiando o contexto pro pool.'\n"
            f"- RUIM (NÃO faça): 'Muito bom, vou estudar isso!', 'Alguém pode "
            f"explicar melhor?', 'Salvando para depois', 'Boa dica!'.\n\n"
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

    def _check_filters(self, payload: str, post_text: str, attempt: int) -> bool:
        """Filtros de qualidade pós-geração. True se o comentário passa."""
        if is_blacklisted(payload):
            logger.info("Comment rejected (blacklisted content)")
            return False
        foreign = foreign_tech_in_comment(payload, post_text)
        if foreign:
            logger.info(
                f"Comment rejected (stack alucinado: {foreign!r} ausente do post) "
                f"tentativa {attempt}: {payload!r}"
            )
            return False
        if not comment_is_grounded(payload, post_text):
            logger.info(
                f"Comment rejected (ungrounded: nada em comum com o post) "
                f"tentativa {attempt}: {payload!r}"
            )
            return False
        if is_trivial(payload):
            logger.info(
                f"Comment rejected (trivial/iniciante) tentativa {attempt}: {payload!r}"
            )
            return False
        if is_junior_tone(payload):
            logger.info(
                f"Comment rejected (tom junior) tentativa {attempt}: {payload!r}"
            )
            return False
        return True

    async def generate_comment(
        self, post_text: str, author: str, variant: str | None = None
    ) -> tuple[str | None, str]:
        """Gera comentário. Retorna ``(texto|None, variant)``.

        Com pipeline ativo (default): Sonnet gera → Fable revisa (pontos
        objetivos) → Sonnet regera → contagem de palavras em Python → Haiku
        comprime se estourar. Sem pipeline: provider único (self.llm).
        """
        variant = variant or self._pick_variant()
        spec = self._VARIANTS.get(variant, self._VARIANTS["insight"])
        min_words, max_words = spec["min_words"], spec["max_words"]
        prompt = self._build_prompt(
            post_text, author, spec["angle"], min_words, max_words
        )
        for attempt in range(2):  # 1 tentativa + 1 retry
            if self.pipeline:
                raw = await self.pipeline.generate(
                    prompt, post_text, min_words=min_words, max_words=max_words
                )
                if raw is None:
                    return None, variant
            else:
                try:
                    raw = await self.llm.complete(prompt)
                except Exception as e:
                    logger.warning(f"generate_comment LLM call failed: {e}")
                    return None, variant
            # Modelo explicou por que não comenta em vez de devolver vazio:
            # é ≈ string vazia. Para já (retry só repetiria a recusa).
            if is_refusal(raw):
                logger.info(f"Comment skip (modelo recusou, ≈ vazio): {raw!r}")
                return None, variant
            ok, payload = validate_comment(
                raw, min_words=min_words, max_words=max_words
            )
            if not ok:
                logger.info(
                    f"Comment rejected ({payload}) tentativa {attempt + 1}: {raw!r}"
                )
                continue
            if not self._check_filters(payload, post_text, attempt + 1):
                continue
            return payload, variant
        return None, variant
