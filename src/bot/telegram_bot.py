import time

from src.config.settings import logger
from src.interfaces.cli.persistence import _find_resume
from src.bot.client import TelegramAuthError, TelegramClient
from src.bot.runner import BrowserTaskRunner
from src.bot.conversation import ConversationFlow
from src.bot.router import UpdateRouter
from src.bot.urls import is_job_url


class TelegramBot:
    """Long-poll Telegram bot — thin orchestrator.

    Wires the transport (:class:`TelegramClient`), the background task
    runner (:class:`BrowserTaskRunner`), the stateful dialog machine
    (:class:`ConversationFlow`) and the command router
    (:class:`UpdateRouter`), then drives the polling loop.
    """

    def __init__(self, resume_path: str = "resume.txt") -> None:
        resolved = _find_resume(resume_path)
        logger.info(f"Resume: {resolved}")
        self.client = TelegramClient()
        self.runner = BrowserTaskRunner(self.client, resolved)
        self.conversation = ConversationFlow(self.client, self.runner)
        self.router = UpdateRouter(self.client, self.runner, self.conversation)

    _MAX_BACKOFF_S = 60

    def run(self) -> None:
        self.client.flush_pending_updates()
        self.client.register_commands()
        self.client.send(
            "🤖 <b>JobPilot online!</b> Digite /help para ver os comandos."
        )
        logger.info("Telegram bot polling started")
        backoff = 1
        while True:
            try:
                updates = self.client.get_updates()
            except TelegramAuthError:
                logger.critical("Credencial do Telegram inválida — bot encerrado")
                return
            except Exception:
                logger.exception(f"Erro no polling, retry em {backoff}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, self._MAX_BACKOFF_S)
                continue
            backoff = 1
            for update in updates:
                # O offset avança sempre — um update que quebra o dispatch não
                # pode ser reentregue em loop e travar o bot.
                self.client.offset = update["update_id"] + 1
                try:
                    self._dispatch(update)
                except Exception:
                    logger.exception("Erro ao processar update")

    def _dispatch(self, update: dict) -> None:
        # callback de botão inline
        if "callback_query" in update:
            cq = update["callback_query"]
            if str(cq["from"]["id"]) == self.client.admin_id:
                self.client.answer_callback(cq["id"])
                self.conversation.handle_callback(cq["data"], cq.get("message"))
            return

        msg = update.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "")
        if chat_id != self.client.admin_id:
            return

        if "document" in msg:
            self.conversation.handle_document(msg["document"])
            return

        if not text:
            return

        if self.conversation.active:
            self.conversation.handle_text(text, self.router.handle_command)
        elif text.startswith("/"):
            self.router.handle_command(text)
        elif is_job_url(text):
            # URL de vaga solta = "vale a pena?". Avalia e responde o veredito.
            self.runner.launch_triage(text.strip())
