"""Tópicos (fórum) do grupo Telegram — roteia cada feature pra sua sessão.

Supergrupos Telegram com modo fórum dividem mensagens em tópicos (threads).
``sendMessage``/``sendPhoto`` aceitam ``message_thread_id`` pra mandar a mensagem
direto na sessão certa. Aqui ficam: a lista de tópicos por feature, o bootstrap
(``createForumTopic`` pros que faltam) e o lookup nome→thread_id, persistido via
``DocRepo`` (backend-aware JSON/Postgres).
"""

import os

from src.config.settings import files_dir, logger
from src.core.persistence.doc_repo import DocRepo
from src.utils.telegram import _post

# (key, título, icon_color). icon_color só aceita um destes 6 valores oficiais.
TOPICS: list[tuple[str, str, int]] = [
    ("report", "📊 Relatórios", 0x6FB9F0),
    ("autopost", "📝 Autopost", 0xFFD67E),
    ("engage", "🤝 Engage", 0xCB86DB),
    ("followup", "💬 Follow-up", 0x8EEE98),
    ("alerts", "🚨 Alertas", 0xFB6F5F),
    ("status", "📡 Status", 0xFF93B2),
]
TOPIC_KEYS = {k for k, _, _ in TOPICS}


class TelegramTopics:
    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.repo = DocRepo(
            "telegram_topics", json_file=files_dir / "telegram_topics.json"
        )

    def _map(self) -> dict[str, int]:
        return self.repo.load().get("topics", {})

    def thread_id(self, key: str | None) -> int | None:
        if not key:
            return None
        return self._map().get(key)

    def bootstrap(self) -> dict[str, int]:
        """Cria os tópicos que ainda não existem e persiste os thread_ids."""
        if not self.token or not self.chat_id:
            logger.warning(
                "TELEGRAM_BOT_TOKEN/CHAT_ID ausentes — não dá p/ criar tópicos"
            )
            return {}
        current = dict(self._map())
        for key, title, color in TOPICS:
            if key in current:
                continue
            tid = self._create(title, color)
            if tid:
                current[key] = tid
        self.repo.save({"topics": current})
        return current

    def reset(self) -> None:
        self.repo.save({"topics": {}})

    def _create(self, title: str, color: int) -> int | None:
        data = _post(
            "createForumTopic",
            label=f"createForumTopic '{title}'",
            json={"chat_id": self.chat_id, "name": title, "icon_color": color},
        )
        if data and data.get("ok"):
            return data["result"]["message_thread_id"]
        logger.warning(f"createForumTopic falhou para {title}")
        return None


def resolve_thread_id(topic: str | None) -> int | None:
    """Lookup tolerante: nunca levanta, retorna None se algo falhar."""
    if not topic:
        return None
    try:
        return TelegramTopics().thread_id(topic)
    except Exception:
        return None
