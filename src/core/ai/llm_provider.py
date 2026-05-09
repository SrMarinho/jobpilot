import os
import time
import subprocess
import urllib.request
from abc import ABC, abstractmethod


def _ensure_ollama_running(base_url: str, timeout: int = 15):
    health = f"{base_url.rstrip('/')}/api/tags"
    try:
        urllib.request.urlopen(health, timeout=3)
        return
    except Exception:
        pass

    from src.config.settings import logger
    logger.info("Ollama not running — starting it...")
    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(health, timeout=2)
            logger.info("Ollama started.")
            return
        except Exception:
            time.sleep(1)

    raise RuntimeError(f"Ollama did not start within {timeout}s at {base_url}")


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, prompt: str) -> str: ...

    def describe(self) -> str:
        return self.__class__.__name__


class ClaudeProvider(LLMProvider):
    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self.model = model

    def describe(self) -> str:
        return f"claude:{self.model}"

    async def complete(self, prompt: str) -> str:
        from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

        result = ""
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(max_turns=1, model=self.model),
        ):
            if isinstance(message, ResultMessage):
                result = message.result.strip()
        return result


class LangChainProvider(LLMProvider):
    def __init__(self, model: str, base_url: str, backend: str = "ollama"):
        self.backend = backend
        self.model = model
        if backend == "deepseek":
            from langchain_deepseek import ChatDeepSeek

            api_key = os.getenv("DEEPSEEK_API_KEY")
            if not api_key:
                raise RuntimeError("DEEPSEEK_API_KEY not set. Run: provider key set deepseek <key>")
            self._llm = ChatDeepSeek(model=model, api_key=api_key, temperature=0)
        else:
            from langchain_ollama import OllamaLLM

            _ensure_ollama_running(base_url)
            self._llm = OllamaLLM(model=model, base_url=base_url)

    def describe(self) -> str:
        return f"langchain[{self.backend}]:{self.model}"

    async def complete(self, prompt: str) -> str:
        result = await self._llm.ainvoke(prompt)
        if hasattr(result, "content"):
            return result.content
        return result


def _build_provider(provider_key: str, model_key: str, base_url_key: str, backend_key: str) -> LLMProvider:
    provider = os.getenv(provider_key, "").lower()
    if not provider:
        provider = os.getenv("LLM_PROVIDER", "claude").lower()

    if provider == "langchain":
        backend = os.getenv(backend_key, "").lower() or os.getenv("LANGCHAIN_BACKEND", "ollama").lower()
        default_model = "deepseek-v4-flash" if backend == "deepseek" else "llama3.2"
        model = os.getenv(model_key) or os.getenv("LANGCHAIN_MODEL", default_model)
        base_url = os.getenv(base_url_key) or os.getenv("LANGCHAIN_BASE_URL", "http://localhost:11434")
        return LangChainProvider(model=model, base_url=base_url, backend=backend)

    model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    return ClaudeProvider(model=model)


def get_llm_provider() -> LLMProvider:
    """Provider for form Q&A (LLM_PROVIDER / LANGCHAIN_MODEL / LANGCHAIN_BACKEND)."""
    return _build_provider("LLM_PROVIDER", "LANGCHAIN_MODEL", "LANGCHAIN_BASE_URL", "LANGCHAIN_BACKEND")


def get_eval_provider() -> LLMProvider:
    """Provider for job evaluation (LLM_PROVIDER_EVAL / LANGCHAIN_MODEL_EVAL / LANGCHAIN_BACKEND_EVAL).
    Falls back to get_llm_provider() settings if not configured."""
    return _build_provider("LLM_PROVIDER_EVAL", "LANGCHAIN_MODEL_EVAL", "LANGCHAIN_BASE_URL", "LANGCHAIN_BACKEND_EVAL")
