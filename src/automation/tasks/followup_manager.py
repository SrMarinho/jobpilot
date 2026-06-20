"""Orquestra o follow-up DM pós-conexão (lado scan — precisa de browser).

Fluxo: abre My Network → conexões recentes → para cada perfil novo (não visto
antes) gera um DM via LLM → registra como pending → manda pro Telegram com
botões de aprovação. O ENVIO acontece depois, no bot persistente (runner),
ao aprovar — espelha o publish-on-approval do autopost.
"""

from playwright.async_api import Page

from src.config.settings import logger
from src.core.ai.llm_provider import LLMProvider
from src.core.use_cases.resume_loader import load_resume_text
from src.core.use_cases.followup_dm import FollowupDMGenerator
from src.core.use_cases.followup_tracker import FollowupTracker


def followup_buttons(draft_id: str) -> list:
    return [
        [
            {"text": "✅ Enviar", "data": f"followup_approve:{draft_id}"},
            {"text": "❌ Descartar", "data": f"followup_reject:{draft_id}"},
        ],
        [
            {"text": "✏️ Editar", "data": f"followup_edit:{draft_id}"},
            {"text": "🔄 Regenerar", "data": f"followup_regen:{draft_id}"},
        ],
    ]


class FollowupManager:
    def __init__(
        self,
        page: Page,
        llm_provider: LLMProvider,
        resume_path: str,
        user_name: str = "",
        user_headline: str = "",
        max_dms: int = 5,
    ):
        self.page = page
        self.max_dms = max_dms
        self.tracker = FollowupTracker()
        self.generator = FollowupDMGenerator(
            llm_provider,
            resume_text=load_resume_text(resume_path),
            user_name=user_name,
            user_headline=user_headline,
        )

    async def scan(self) -> int:
        """Scrape conexões recentes → gera drafts → manda pro Telegram.

        Retorna o número de drafts criados.
        """
        from src.automation.pages.connections_page import ConnectionsPage
        from src.utils.telegram import send_telegram_buttons

        page_obj = ConnectionsPage(self.page)
        connections = await page_obj.recent_connections(limit=self.max_dms * 3)
        created = 0
        for conn in connections:
            if created >= self.max_dms:
                break
            profile_url = conn.get("profile_url", "")
            if not profile_url or self.tracker.already_seen(profile_url):
                continue
            name = conn.get("name", "")
            headline = conn.get("headline", "")
            content = await self.generator.generate(name, headline)
            if not content:
                logger.info(f"Sem DM válido p/ {name!r}, pulando")
                continue
            draft_id = self.tracker.add_draft(name, profile_url, headline, content)
            header = (
                f"💬 <b>Follow-up DM</b>\n<b>{name}</b>\n<i>{headline[:80]}</i>\n\n"
            )
            try:
                send_telegram_buttons(header + content, followup_buttons(draft_id))
            except Exception as e:
                logger.warning(f"Falha ao enviar DM draft p/ aprovação: {e}")
            created += 1

        if created == 0:
            logger.info("Follow-up: nenhuma conexão nova p/ DM")
            try:
                from src.utils.telegram import send_telegram

                send_telegram("💬 <b>Follow-up</b>: nenhuma conexão nova encontrada.")
            except Exception:
                pass
        else:
            logger.info(f"Follow-up: {created} drafts enviados p/ aprovação")
        return created
