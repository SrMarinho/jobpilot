"""Generate authored LinkedIn posts via LLM.

Mirrors ``engagement_handler``: module-level validation helpers + a class
that builds the prompt and validates the output. Reuses
``load_resume_text``/``is_blacklisted`` so resume parsing and topic
blacklisting stay in one place.
"""

import re

from src.config.settings import logger
from src.core.ai.llm_provider import LLMProvider
from src.core.use_cases.content_filters import is_blacklisted

_MIN_CHARS = 80
# Só o limite real da plataforma (LinkedIn = 3000). O tamanho ideal não é
# ditado em número: o prompt declara a plataforma e o modelo aplica as
# convenções dela (dobra "ver mais", mobile-first etc).
_HARD_CAP_CHARS = 3000
# TODO/FIXME são marcadores de código → match SÓ em maiúsculas (case-sensitive),
# senão a palavra PT-BR "todo"/"toda" (= "all") derruba posts legítimos. Os
# placeholders em <> ficam case-insensitive.
_PLACEHOLDER_RE = re.compile(r"\bTODO\b|\bFIXME\b|(?i:<\.\.\.>|<placeholder>)")
_HASHTAG_RE = re.compile(r"#\w+")

_FORMAT_GUIDE = {
    "snippet": "1 dica técnica em poucas linhas. Direto ao ponto, quase um código comentado em prosa. Formato naturalmente CURTO.",
    "story": "situação → ação → lição, conciso. Tom de build-in-public. Formato de tamanho médio.",
    "dissertativo": "tese + argumento desenvolvido + conclusão. Opinião técnica fundamentada, com espaço pra explicar o mecanismo. Formato que sustenta mais desenvolvimento.",
    "contrarian": (
        "uma tese não-óbvia e PRECISA (não slogan, não absolutismo) + o reasoning "
        "+ a condição em que vale E a exceção em que não vale + convite ao debate "
        "técnico. Deve sobreviver ao 'well, actually' de um sênior."
    ),
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
        reviewer: LLMProvider | None = None,
        platform: str = "LinkedIn",
    ):
        self.llm = llm_provider
        # Revisor opcional (critic loop): gera → review → reescreve. Em LLM local
        # passa o mesmo provider (auto-crítica); no cloud, ex.: gera=haiku,
        # review=opus, reescreve=haiku. None = sem review (gera direto).
        self.reviewer = reviewer
        self.resume = resume_text or ""  # completo (sem corte)
        self.user_name = user_name or "profissional de tecnologia"
        self.user_headline = (
            user_headline or "Software Engineer focado em Python e Node.js"
        )
        # Plataforma-alvo: o prompt declara onde o post vai ser publicado e o
        # modelo aplica as convenções (tamanho, formatação, hashtags) sozinho.
        self.platform = platform or "LinkedIn"

    def _build_prompt(self, topic: str, fmt: str, context: str, brief: str = "") -> str:
        guide = _FORMAT_GUIDE.get(fmt, _FORMAT_GUIDE["dissertativo"])
        ctx_block = (
            f'\nMaterial de apoio:\n"""\n{context[:800]}\n"""\n' if context else ""
        )
        # Direção livre do autor: tema + detalhes/ângulo que o post deve seguir.
        # Tem prioridade sobre o tema genérico — é a intenção explícita do autor.
        brief_block = (
            f'\nDireção do autor (SIGA esta orientação, ela tem prioridade):\n"""\n'
            f'{brief[:2000]}\n"""\n'
            if brief
            else ""
        )
        return (
            f"Você é {self.user_name}, {self.user_headline}.\n"
            f"Escreva um post autoral para o {self.platform}, em primeira pessoa.\n\n"
            f"Currículo completo (use para dar autenticidade):\n{self.resume}\n\n"
            f"Tema: {topic}\n"
            f"Formato: {fmt} — {guide}\n"
            f"{brief_block}"
            f"{ctx_block}\n"
            f"Público: engenheiros sêniores. Assuma que já sabem o básico — "
            f"NÃO explique conceitos elementares nem defina termos.\n\n"
            f"Regras estritas:\n"
            f"- Isto é um post {fmt} para o {self.platform}: aplique as "
            f"convenções da plataforma PARA esse tipo de post (tamanho "
            f"natural do formato, dobra do 'ver mais', formatação que "
            f"performa lá). Um snippet é curto; um dissertativo sustenta "
            f"mais desenvolvimento. Longo o bastante pra explicar bem, "
            f"curto o bastante pra ser lido até o fim.\n"
            f"- Primeira linha = hook forte (contrarian, número, vulnerabilidade ou pergunta).\n"
            f"- Toda frase carrega peso. Zero filler.\n"
            f"- UMA ideia central, desenvolvida com fio condutor: cada frase "
            f"decorre da anterior. Explicar 1 mecanismo bem > citar 3 por alto.\n"
            f"- Jargão não substitui explicação: ao nomear um conceito, mostre "
            f"em palavras simples o que ele faz na prática. Nada de lista de "
            f"termos técnicos soltos.\n"
            f"- Quebras de linha frequentes (mobile-first).\n"
            f"- Encerre com uma pergunta ou CTA curto.\n"
            f"- 2-4 hashtags relevantes e específicas (nada genérico como #Engenharia).\n"
            f"- SEM emojis em excesso (no máximo 1).\n"
            f"- NÃO mencione que está procurando emprego.\n"
            f"# Profundidade e honestidade (evitar parecer júnior / clickbait):\n"
            f"- SEM absolutismo: evite 'sempre', 'nunca', 'X não é Y'. Tese forte "
            f"vem com a condição em que vale e a exceção em que não vale.\n"
            f"- Mostre o MECANISMO e o trade-off real, não só o erro ou o slogan.\n"
            f"- NÃO sinalize status (nada de 'isso me fez sênior', 'júnior faz X').\n"
            f"- Profundidade sobre choque: prefira o insight não-óbvio à frase de efeito.\n\n"
            f"Retorne APENAS o texto do post, sem preâmbulo, sem aspas.\n"
            f"Post:"
        )

    def _review_prompt(self, post: str, topic: str, fmt: str) -> str:
        return (
            f"Você é um editor técnico sênior de conteúdo para {self.platform}.\n"
            "Critique o post abaixo para um público de engenheiros SÊNIORES.\n\n"
            f"Tema: {topic}\nFormato: {fmt}\n\n"
            f"Critérios:\n"
            f"- Tamanho adequado: é um post {fmt} para o {self.platform} — o "
            f"formato define o tamanho natural.\n"
            "- Sem absolutismo/clickbait: tese forte vem com condição e exceção.\n"
            "- Profundidade real (mecanismo, trade-off), não slogan nem o básico.\n"
            "- Não sinaliza status ('isso me fez sênior', 'júnior faz X').\n"
            "- Hook forte, frases com peso, mobile-first, CTA genuíno.\n"
            "- FIO CONDUTOR: uma ideia desenvolvida de ponta a ponta, frases "
            "conectadas causalmente. Post que vira lista de termos técnicos "
            "soltos e desconectados é defeito grave — aponte.\n"
            "- 2-4 hashtags específicas. Deve sobreviver ao 'well, actually' de um sênior.\n\n"
            f'Post:\n"""\n{post}\n"""\n\n'
            "Se já está excelente, responda APENAS: OK\n"
            "Senão, liste 2 a 5 problemas concretos e acionáveis (bullets curtos). "
            "NÃO reescreva o post, só aponte os problemas."
        )

    def _rewrite_prompt(
        self,
        topic: str,
        fmt: str,
        context: str,
        prev: str,
        feedback: str,
        brief: str = "",
    ) -> str:
        base = self._build_prompt(topic, fmt, context, brief).rsplit("Post:", 1)[0]
        return (
            base
            + "Versão anterior do post:\n"
            + prev
            + "\n\nFeedback do editor (incorpore TUDO):\n"
            + feedback
            + "\n\nReescreva o post incorporando o feedback. Se o feedback pede "
            + "mais profundidade do que cabe no limite, CORTE ideias inteiras e "
            + "desenvolva menos pontos melhor — NÃO esprema tudo em frases "
            + "telegráficas desconectadas. "
            + "Retorne APENAS o post reescrito, sem preâmbulo, sem aspas.\nPost:"
        )

    def _shrink_prompt(self, text: str) -> str:
        # Modelo não conta caracteres: retry cego regera outro texto longo.
        # Comprimir o texto que já existe converge (mesmo padrão do
        # comment_pipeline, que conta em Python e delega só o corte).
        return (
            f"O post de {self.platform} abaixo tem {len(text)} caracteres; o "
            f"limite duro da plataforma é {_HARD_CAP_CHARS}. Reescreva-o com "
            f"NO MÁXIMO {_HARD_CAP_CHARS - 500} "
            "caracteres. Mantenha o hook, a substância técnica e as hashtags; "
            "corte IDEIAS inteiras, não as conexões entre frases — o texto "
            "final deve continuar fluido, não telegráfico. NÃO adicione nada "
            "novo.\n\n"
            f'"""\n{text}\n"""\n\n'
            "Retorne APENAS o post reescrito, sem preâmbulo, sem aspas.\nPost:"
        )

    async def _complete_valid(self, prompt: str, fmt: str, retries: int) -> str | None:
        """Chama o gerador, limpa <think>, valida. Retorna texto ou None."""
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
                return payload
            logger.info(
                f"Draft rejeitado ({payload}) tentativa {attempt + 1}/{retries + 1}"
            )
            if payload.startswith("too long") and raw:
                prompt = self._shrink_prompt(raw)
        return None

    async def generate_draft(
        self,
        topic: str,
        fmt: str,
        context: str = "",
        retries: int = 1,
        brief: str = "",
    ) -> str | None:
        # 1) gera
        draft = await self._complete_valid(
            self._build_prompt(topic, fmt, context, brief), fmt, retries
        )
        if not draft:
            return None
        logger.info(f"Draft gerado ({len(draft)} chars, format={fmt})")

        # 2) review + reescreve (se houver reviewer)
        if self.reviewer is not None:
            try:
                feedback = (
                    await self.reviewer.complete(self._review_prompt(draft, topic, fmt))
                ) or ""
                feedback = re.sub(
                    r"<think>.*?</think>", "", feedback, flags=re.DOTALL
                ).strip()
            except Exception as e:
                logger.warning(f"review falhou (segue sem): {e}")
                feedback = "OK"
            if feedback and feedback.strip().upper() != "OK":
                logger.info(f"Review apontou ajustes:\n{feedback}")
                rewritten = await self._complete_valid(
                    self._rewrite_prompt(topic, fmt, context, draft, feedback, brief),
                    fmt,
                    retries,
                )
                if rewritten:
                    logger.info(f"Draft reescrito ({len(rewritten)} chars)")
                    return rewritten
                logger.info("Reescrita inválida; mantém versão original")
            else:
                logger.info("Review: OK (sem reescrita)")
        return draft
