import os
import requests

from src.config.settings import logger


class TelegramAuthError(RuntimeError):
    """Token inválido/revogado — retry não resolve, o bot precisa parar."""


class TelegramClient:
    """Pure Telegram HTTP transport — no business logic.

    Owns the bot credentials, the Bot API base URL and the long-poll
    ``offset`` cursor. Every method maps to a single Telegram endpoint;
    callers stay free of ``requests`` and URL-building details.
    """

    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = str(os.getenv("TELEGRAM_CHAT_ID"))
        self.admin_id = str(
            os.getenv("TELEGRAM_ADMIN_ID", os.getenv("TELEGRAM_CHAT_ID"))
        )
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.offset = 0

    # ── Outbound ──────────────────────────────────────────────────────────────

    @staticmethod
    def _thread(topic: str | None) -> int | None:
        from src.core.use_cases.telegram_topics import resolve_thread_id

        return resolve_thread_id(topic)

    def send(
        self, text: str, buttons: list | None = None, topic: str | None = None
    ) -> None:
        thread = self._thread(topic)
        payload: dict = {
            "chat_id": self.chat_id if thread else self.admin_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if thread:
            payload["message_thread_id"] = thread
        if buttons:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": b["text"], "callback_data": b["data"]} for b in row]
                    for row in buttons
                ]
            }
        try:
            requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
        except Exception as e:
            logger.warning(f"Failed to send Telegram message: {e}")

    def send_notification(self, text: str, topic: str | None = None) -> None:
        payload: dict = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        thread = self._thread(topic)
        if thread:
            payload["message_thread_id"] = thread
        try:
            requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

    def edit_reply_markup(self, chat_id, message_id) -> None:
        """Remove os botões inline de uma mensagem já enviada."""
        try:
            requests.post(
                f"{self.base_url}/editMessageReplyMarkup",
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "reply_markup": {"inline_keyboard": []},
                },
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"Failed to edit reply markup: {e}")

    def answer_callback(self, callback_query_id: str) -> None:
        try:
            requests.post(
                f"{self.base_url}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id},
                timeout=10,
            )
        except Exception:
            pass

    # ── Inbound ───────────────────────────────────────────────────────────────

    def get_updates(self, timeout: int = 30) -> list:
        """Long-poll de updates.

        Distingue falha de rede (transitória → ``[]``, o loop tenta de novo) de
        falha de credencial (``TelegramAuthError``, que para o bot em vez de
        virar um hot spin invisível).
        """
        try:
            resp = requests.get(
                f"{self.base_url}/getUpdates",
                params={
                    "offset": self.offset,
                    "timeout": timeout,
                    "allowed_updates": ["message", "callback_query"],
                },
                timeout=timeout + 5,
            )
        except requests.RequestException as e:
            logger.warning(f"getUpdates: falha de rede ({e})")
            return []
        if resp.status_code in (401, 403, 404):
            raise TelegramAuthError(
                f"getUpdates HTTP {resp.status_code} — TELEGRAM_BOT_TOKEN inválido"
            )
        try:
            return resp.json().get("result", [])
        except Exception as e:
            logger.warning(f"getUpdates: resposta ilegível ({e})")
            return []

    def flush_pending_updates(self) -> None:
        """Discard all updates that arrived before this startup."""
        try:
            resp = (
                requests.get(
                    f"{self.base_url}/getUpdates",
                    params={"offset": -1, "timeout": 0},
                    timeout=10,
                )
                .json()
                .get("result", [])
            )
            if resp:
                self.offset = resp[-1]["update_id"] + 1
        except Exception:
            pass

    # ── Files ─────────────────────────────────────────────────────────────────

    def download_file(self, file_id: str) -> bytes:
        """Resolve a Telegram ``file_id`` and download its raw bytes."""
        file_info = requests.get(
            f"{self.base_url}/getFile",
            params={"file_id": file_id},
            timeout=10,
        ).json()["result"]
        file_path = file_info["file_path"]
        return requests.get(
            f"https://api.telegram.org/file/bot{self.token}/{file_path}",
            timeout=30,
        ).content

    # ── Setup ─────────────────────────────────────────────────────────────────

    def register_commands(self) -> None:
        try:
            requests.post(
                f"{self.base_url}/setMyCommands",
                json={
                    "commands": [
                        {"command": "connect", "description": "Enviar conexões"},
                        {
                            "command": "apply",
                            "description": "Aplicar vagas — /apply <url>",
                        },
                        {
                            "command": "engage",
                            "description": "Engajar no feed (com aprovação)",
                        },
                        {"command": "autopost", "description": "Gerar post autoral"},
                        {
                            "command": "autopost_topic",
                            "description": "Post com tema — /autopost_topic <tema>",
                        },
                        {
                            "command": "autopost_list",
                            "description": "Últimos posts + drafts pendentes",
                        },
                        {
                            "command": "followup",
                            "description": "DMs pós-conexão p/ aprovar",
                        },
                        {"command": "resume", "description": "Atualizar currículo"},
                        {
                            "command": "status",
                            "description": "Ver se tem tarefa rodando",
                        },
                        {"command": "stop", "description": "Parar tarefa atual"},
                        {
                            "command": "ping",
                            "description": "Verificar se o bot está vivo",
                        },
                        {"command": "reiniciar", "description": "Reiniciar o bot"},
                        {"command": "help", "description": "Ver todos os comandos"},
                    ]
                },
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"Failed to register commands: {e}")
