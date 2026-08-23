"""Decide a resposta de uma pergunta do formulário: cache primeiro, LLM depois.

Sem nenhuma dependência de DOM — recebe a pergunta como texto e devolve a
resposta como texto. É por isso que LinkedIn/Glassdoor e Indeed compartilham
esta peça em vez de cada um ter a sua cópia de ``_ask_llm`` + cache.
"""

import asyncio

from src.config.settings import logger
from src.core.ai.llm_provider import LLMProvider, get_llm_provider
from src.core.use_cases.form_answer_cache import FormAnswerCache

MAX_DESCRIPTION_CHARS = 1500

# O prompt pede "only the value", mas quando falta o dado o modelo escreve uma
# recusa em vez de um valor. Sem esse filtro a recusa vira "resposta", vai pro
# cache e passa a ser digitada em todo formulario — foi o que travou o Easy
# Apply preenchendo "No phone number in profile data..." no campo de celular.
_REFUSAL_MARKERS = (
    "can't fabricate",
    "cannot fabricate",
    "can't provide",
    "cannot provide",
    "can't fill",
    "cannot fill",
    "don't have",
    "do not have",
    "not provided",
    "no phone number",
    "need actual",
    "as an ai",
    "i'm unable",
    "i am unable",
    "nao posso",
    "não posso",
    "nao tenho",
    "não tenho",
    "nao informado",
    "não informado",
)

# Dado pessoal nao passa pelo LLM: ou esta configurado, ou o campo fica vazio.
# Telefone e o caso que trava o Easy Apply — campo obrigatorio, sem fonte no
# curriculo, e o modelo respondendo com uma recusa em vez de um numero.
_PHONE_MARKERS = ("celular", "telefone", "phone", "mobile", "whatsapp")
# "Codigo do pais do telefone" e outro campo (um select), nao o numero.
_PHONE_EXCLUSIONS = ("codigo", "código", "country code", "ddi")


def personal_answer(question: str) -> str | None:
    """Resposta vinda da config do usuario, ou ``None`` se nao for esse caso."""
    from src.config import sections as settings_sections

    q = question.strip().lower()
    if any(x in q for x in _PHONE_EXCLUSIONS):
        return None
    if any(m in q for m in _PHONE_MARKERS):
        return settings_sections.user.phone or None
    return None


# Valor de formulario e curto. Um paragrafo e explicacao, nao resposta.
_MAX_ANSWER_CHARS = 300


def looks_like_refusal(answer: str) -> bool:
    """``True`` quando o texto e recusa/explicacao, nao um valor preenchivel."""
    text = answer.strip().lower()
    if not text:
        return False
    if any(m in text for m in _REFUSAL_MARKERS):
        return True
    return len(text) > _MAX_ANSWER_CHARS


class FormAnswerer:
    def __init__(
        self, cache: FormAnswerCache | None = None, provider: LLMProvider | None = None
    ):
        self._cache = cache or FormAnswerCache()
        # Injetável p/ teste; None = resolvido sob demanda em ``provider()``.
        self._provider = provider

    # ── Cache ────────────────────────────────────────────────────────────────

    def resolve(self, question: str) -> str | None:
        """Resposta já conhecida pra essa pergunta, ou ``None``.

        Recusas gravadas antes do filtro existir continuam no cache; descartar
        na leitura conserta o histórico sem precisar mexer no banco.
        """
        cached = self._cache.resolve(question)
        if cached and looks_like_refusal(cached):
            logger.warning(
                f"Cache de formulário tem uma recusa em '{question[:50]}', ignorando"
            )
            return None
        return cached

    def store(self, question: str, answer: str, options: list | None = None) -> None:
        self._cache.store(question, answer, options=options)

    # ── LLM ──────────────────────────────────────────────────────────────────

    async def provider(self) -> LLMProvider:
        """Provider lazy + memoizado, construído fora do event loop.

        ``get_llm_provider()`` pode bloquear até 15s subindo o Ollama; construir
        a cada pergunta travaria o browser junto.
        """
        if self._provider is None:
            self._provider = await asyncio.to_thread(get_llm_provider)
        return self._provider

    async def ask(self, question: str, job_title: str, job_description: str) -> str:
        """Resposta do LLM pra uma pergunta de formulário. ``""`` se falhar."""
        model = await self.provider()
        prompt = (
            f"You are applying for the job '{job_title}'. "
            f"Job description: {job_description[:MAX_DESCRIPTION_CHARS]}\n"
            f"Answer the following question concisely for a job application form: {question}\n"
            f"Answer with only the value, no explanation."
        )
        try:
            answer = await model.complete(prompt)
        except Exception as e:
            logger.error(f"LLM error on '{question[:50]}': {e}")
            return ""
        if looks_like_refusal(answer):
            # Melhor campo vazio que campo com a recusa escrita dentro: o
            # LinkedIn rejeita o valor e o formulario nunca avanca.
            logger.warning(
                f"LLM nao respondeu com um valor para '{question[:50]}': "
                f"{answer.strip()[:80]!r}"
            )
            return ""
        return answer

    async def answer(
        self,
        question: str,
        job_title: str,
        job_description: str,
        *,
        options: list | None = None,
    ) -> tuple[str, bool]:
        """Resposta pra ``question`` e se veio do cache.

        Com ``options``, a lista entra no prompt pro LLM escolher entre elas.
        O ``from_cache`` importa porque só resposta nova precisa ser gravada.
        """
        known = personal_answer(question)
        if known:
            # True: já é um valor definitivo, não precisa ser regravado.
            return known, True
        cached = self.resolve(question)
        if cached:
            return cached, True
        prompt_question = f"{question} (options: {options})" if options else question
        return await self.ask(prompt_question, job_title, job_description), False
