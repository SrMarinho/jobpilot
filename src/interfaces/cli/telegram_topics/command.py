import sys

import typer


def _out(text: str) -> None:
    """Escreve em UTF-8 direto no buffer (console cp1252 quebra com emoji/→)."""
    sys.stdout.buffer.write((text + "\n").encode("utf-8", "replace"))


def register_telegram_topics_commands(app: typer.Typer) -> None:
    @app.command()
    def setup() -> None:
        """Cria os tópicos (sessões) do grupo fórum e salva os thread_ids."""
        from src.core.use_cases.telegram_topics import TOPICS, TelegramTopics

        result = TelegramTopics().bootstrap()
        if not result:
            _out(
                "Nenhum tópico criado. Verifique TELEGRAM_BOT_TOKEN/CHAT_ID e se o "
                "grupo está em modo fórum (Tópicos ativados nas configs do grupo)."
            )
            return
        _out("Tópicos prontos:")
        for key, title, _ in TOPICS:
            tid = result.get(key)
            _out(f"  {key:10} -> {title}  (thread_id={tid})")

    @app.command(name="list")
    def list_topics() -> None:
        """Mostra os tópicos configurados e seus thread_ids."""
        from src.core.use_cases.telegram_topics import TOPICS, TelegramTopics

        topics = TelegramTopics()
        _out("Tópicos:")
        for key, title, _ in TOPICS:
            tid = topics.thread_id(key)
            mark = tid if tid else "— (não criado)"
            _out(f"  {key:10} -> {title}  {mark}")

    @app.command()
    def reset() -> None:
        """Limpa os thread_ids salvos (não apaga os tópicos no Telegram)."""
        from src.core.use_cases.telegram_topics import TelegramTopics

        TelegramTopics().reset()
        _out("Mapa de tópicos limpo. Rode 'setup' para recriar/remapear.")
