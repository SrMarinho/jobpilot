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


class FormAnswerer:
    def __init__(
        self, cache: FormAnswerCache | None = None, provider: LLMProvider | None = None
    ):
        self._cache = cache or FormAnswerCache()
        # Injetável p/ teste; None = resolvido sob demanda em ``provider()``.
        self._provider = provider

    # ── Cache ────────────────────────────────────────────────────────────────

    def resolve(self, question: str) -> str | None:
        """Resposta já conhecida pra essa pergunta, ou ``None``."""
        return self._cache.resolve(question)

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
            return await model.complete(prompt)
        except Exception as e:
            logger.error(f"LLM error on '{question[:50]}': {e}")
            return ""

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
        cached = self.resolve(question)
        if cached:
            return cached, True
        prompt_question = f"{question} (options: {options})" if options else question
        return await self.ask(prompt_question, job_title, job_description), False
