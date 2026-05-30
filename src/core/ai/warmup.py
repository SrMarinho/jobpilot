import os
import asyncio

from src.config.settings import logger


def apply_provider_overrides(
    llm_provider: str | None = None,
    llm_model: str | None = None,
    eval_provider: str | None = None,
    eval_model: str | None = None,
) -> None:
    """Set LLM_PROVIDER / LLM_PROVIDER_EVAL env vars from CLI overrides."""
    if llm_provider:
        os.environ["LLM_PROVIDER"] = llm_provider
        logger.info(f"[override] LLM_PROVIDER={llm_provider}")
    if llm_model:
        key = (
            "LANGCHAIN_MODEL"
            if os.environ.get("LLM_PROVIDER") == "langchain"
            else "CLAUDE_MODEL"
        )
        os.environ[key] = llm_model
        logger.info(f"[override] {key}={llm_model}")
    if eval_provider:
        os.environ["LLM_PROVIDER_EVAL"] = eval_provider
        logger.info(f"[override] LLM_PROVIDER_EVAL={eval_provider}")
    if eval_model:
        key = (
            "LANGCHAIN_MODEL_EVAL"
            if os.environ.get("LLM_PROVIDER_EVAL") == "langchain"
            else "CLAUDE_MODEL"
        )
        os.environ[key] = eval_model
        logger.info(f"[override] {key}={eval_model}")


def warmup_llm_providers() -> None:
    """Instantiate and warm up both LLM and eval providers."""
    from src.core.ai.llm_provider import get_llm_provider, get_eval_provider
    from src.utils.async_utils import run_async

    llm = get_llm_provider()
    evl = get_eval_provider()
    logger.info(f"LLM:  {llm.describe()}")
    logger.info(f"EVAL: {evl.describe()}")
    logger.info("Warming up LLM models...")

    async def _warmup():
        async def _try(name: str, prov):
            try:
                await prov.complete("hi")
                logger.info(f"Warmup OK: {name}")
            except Exception as e:
                logger.warning(f"Warmup failed for {name}: {e}")

        await asyncio.gather(
            _try("llm", llm),
            _try("eval", evl),
        )

    run_async(_warmup())
    logger.info("LLM models ready.")
