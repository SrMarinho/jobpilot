import asyncio
import os
import time
import subprocess
import urllib.request
from abc import ABC, abstractmethod

from src.core.ai.llm_errors import is_model_unavailable, is_transient

# Uma falha passageira raramente dura mais que alguns segundos; o run inteiro
# tem orçamento de minutos, então três tentativas curtas é o teto útil.
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_S = 2


def _ensure_ollama_running(base_url: str, timeout: int = 15):
    health = f"{base_url.rstrip('/')}/api/tags"
    try:
        urllib.request.urlopen(health, timeout=3)
        return
    except Exception:
        pass

    from src.config.settings import logger

    logger.info("Ollama not running — starting it...")
    subprocess.Popen(
        ["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(health, timeout=2)
            logger.info("Ollama started.")
            return
        except Exception:
            time.sleep(1)

    raise RuntimeError(f"Ollama did not start within {timeout}s at {base_url}")


def _split_models(raw: str) -> list[str]:
    return [m.strip() for m in raw.split(",") if m.strip()]


class LLMProvider(ABC):
    """Contrato mínimo de um provider: dado um prompt, devolve texto."""

    @abstractmethod
    async def complete(self, prompt: str) -> str: ...

    def describe(self) -> str:
        return self.__class__.__name__


class ResilientProvider(LLMProvider):
    """Política de resiliência compartilhada pelos providers reais.

    Subclasse implementa `_complete_with(model, prompt)`; a cadeia de modelos e
    o retry ficam aqui para que Claude e LangChain falhem do mesmo jeito. Fica
    separado de `LLMProvider` porque dublês de teste implementam só `complete`.
    """

    models: list[str]

    @abstractmethod
    async def _complete_with(self, model: str, prompt: str) -> str: ...

    async def complete(self, prompt: str) -> str:
        from src.config.settings import logger

        last: Exception | None = None
        for index, model in enumerate(self.models):
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    result = await self._complete_with(model, prompt)
                    if index > 0:
                        logger.warning(
                            f"LLM: modelo '{self.models[0]}' indisponível — "
                            f"'{model}' assumiu"
                        )
                    return result
                except Exception as e:
                    last = e
                    if is_transient(e) and attempt < _MAX_ATTEMPTS:
                        wait = _BACKOFF_BASE_S * (2 ** (attempt - 1))
                        logger.warning(
                            f"LLM '{model}' falhou ({e}); nova tentativa em {wait}s "
                            f"({attempt}/{_MAX_ATTEMPTS})"
                        )
                        await asyncio.sleep(wait)
                        continue
                    if is_model_unavailable(e):
                        logger.warning(f"LLM '{model}' indisponível: {e}")
                    break
        raise last if last else RuntimeError("Nenhum modelo LLM configurado")


class ClaudeProvider(ResilientProvider):
    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        fallbacks: list[str] | None = None,
    ):
        self.model = model
        if fallbacks is None:
            fallbacks = _split_models(os.getenv("CLAUDE_MODEL_FALLBACKS", ""))
        # Haiku fecha a cadeia: é o degrau mais barato e o que menos depende de
        # plano/rollout, então serve de último recurso quando o resto some.
        chain = [model, *fallbacks, "claude-haiku-4-5-20251001"]
        self.models = list(dict.fromkeys(chain))

    def describe(self) -> str:
        return f"claude:{self.model}"

    async def _complete_with(self, model: str, prompt: str) -> str:
        from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

        result = ""
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(max_turns=1, model=model),
        ):
            if isinstance(message, ResultMessage):
                result = message.result.strip()
        return result


class LangChainProvider(ResilientProvider):
    def __init__(
        self,
        model: str,
        base_url: str,
        backend: str = "ollama",
        fallbacks: list[str] | None = None,
    ):
        self.backend = backend
        self.model = model
        self.base_url = base_url
        if fallbacks is None:
            fallbacks = _split_models(os.getenv("LANGCHAIN_MODEL_FALLBACKS", ""))
        self.models = list(dict.fromkeys([model, *fallbacks]))
        self._clients: dict[str, object] = {}

    def _build(self, model: str):
        if model in self._clients:
            return self._clients[model]
        if self.backend == "deepseek":
            from langchain_deepseek import ChatDeepSeek

            api_key = os.getenv("DEEPSEEK_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "DEEPSEEK_API_KEY not set. Run: provider key set deepseek <key>"
                )
            llm = ChatDeepSeek(model=model, api_key=api_key, temperature=0)
        else:
            from langchain_ollama import OllamaLLM

            _ensure_ollama_running(self.base_url)
            llm = OllamaLLM(model=model, base_url=self.base_url)
        self._clients[model] = llm
        return llm

    def describe(self) -> str:
        return f"langchain[{self.backend}]:{self.model}"

    async def _complete_with(self, model: str, prompt: str) -> str:
        result = await self._build(model).ainvoke(prompt)
        if hasattr(result, "content"):
            return result.content
        return result


def _build_provider(
    provider_key: str, model_key: str, base_url_key: str, backend_key: str
) -> LLMProvider:
    provider = os.getenv(provider_key, "").lower()
    if not provider:
        provider = os.getenv("LLM_PROVIDER", "claude").lower()

    if provider == "langchain":
        backend = (
            os.getenv(backend_key, "").lower()
            or os.getenv("LANGCHAIN_BACKEND", "ollama").lower()
        )
        default_model = "deepseek-v4-flash" if backend == "deepseek" else "llama3.2"
        model = os.getenv(model_key) or os.getenv("LANGCHAIN_MODEL", default_model)
        base_url = os.getenv(base_url_key) or os.getenv(
            "LANGCHAIN_BASE_URL", "http://localhost:11434"
        )
        return LangChainProvider(model=model, base_url=base_url, backend=backend)

    model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    return ClaudeProvider(model=model)


def get_llm_provider() -> LLMProvider:
    """Provider for form Q&A (LLM_PROVIDER / LANGCHAIN_MODEL / LANGCHAIN_BACKEND)."""
    return _build_provider(
        "LLM_PROVIDER", "LANGCHAIN_MODEL", "LANGCHAIN_BASE_URL", "LANGCHAIN_BACKEND"
    )


def get_eval_provider() -> LLMProvider:
    """Provider for job evaluation (LLM_PROVIDER_EVAL / LANGCHAIN_MODEL_EVAL / LANGCHAIN_BACKEND_EVAL).
    Falls back to get_llm_provider() settings if not configured."""
    return _build_provider(
        "LLM_PROVIDER_EVAL",
        "LANGCHAIN_MODEL_EVAL",
        "LANGCHAIN_BASE_URL",
        "LANGCHAIN_BACKEND_EVAL",
    )
