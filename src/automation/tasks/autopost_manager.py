"""Autopost orchestration — draft generation side (no browser).

Publishing is intentionally NOT here: a scheduled CLI run generates a draft,
hands it to Telegram for human approval and exits; the persistent bot opens
the browser and publishes on approval (see ``src/bot/runner.py``). The
``FeedComposerPage`` does the actual DOM work.
"""

from src.config.settings import logger
from src.core.ai.llm_provider import LLMProvider
from src.core.use_cases.resume_loader import load_resume_text
from src.core.use_cases.post_drafter import PostDrafter
from src.core.use_cases.post_sources import (
    pick_content,
    default_source_for_today,
    default_format_for_today,
)


class AutopostManager:
    def __init__(
        self,
        llm_provider: LLMProvider,
        resume_path: str,
        user_name: str = "",
        user_headline: str = "",
        source: str | None = None,
        topic: str | None = None,
        fmt: str | None = None,
        recent: set[str] | None = None,
        reviewer: LLMProvider | None = None,
        brief: str = "",
    ):
        self.drafter = PostDrafter(
            llm_provider,
            load_resume_text(resume_path),
            user_name=user_name,
            user_headline=user_headline,
            reviewer=reviewer,
        )
        self.source = source or default_source_for_today()
        self.topic = topic
        self.fmt = fmt or default_format_for_today()
        self.recent = recent or set()
        # Direção livre do autor (tema + detalhes/ângulo); vai direto ao prompt.
        self.brief = brief or ""

    async def generate(self) -> dict | None:
        """Resolve source → draft → validate. Returns a draft payload dict."""
        resolved_topic, context = pick_content(self.source, self.topic, self.recent)
        logger.info(
            f"Autopost gerando: source={self.source} format={self.fmt} "
            f"topic={resolved_topic!r}"
        )
        content = await self.drafter.generate_draft(
            resolved_topic, self.fmt, context, brief=self.brief
        )
        if not content:
            logger.warning("Autopost: nenhum draft válido gerado")
            return None
        return {
            "source": self.source,
            "format": self.fmt,
            "topic": resolved_topic,
            "content": content,
        }
