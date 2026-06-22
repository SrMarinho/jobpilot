import typer


def register_telegram_topics_commands(app: typer.Typer) -> None:
    @app.command()
    def setup() -> None:
        """Cria os tópicos (sessões) do grupo fórum e salva os thread_ids."""
        from src.core.use_cases.telegram_topics import TOPICS, TelegramTopics

        result = TelegramTopics().bootstrap()
        if not result:
            print(
                "Nenhum tópico criado. Verifique TELEGRAM_BOT_TOKEN/CHAT_ID e se o "
                "grupo está em modo fórum (Tópicos ativados nas configs do grupo)."
            )
            return
        print("Tópicos prontos:")
        for key, title, _ in TOPICS:
            tid = result.get(key)
            print(f"  {key:10} → {title}  (thread_id={tid})")

    @app.command(name="list")
    def list_topics() -> None:
        """Mostra os tópicos configurados e seus thread_ids."""
        from src.core.use_cases.telegram_topics import TOPICS, TelegramTopics

        topics = TelegramTopics()
        print("Tópicos:")
        for key, title, _ in TOPICS:
            tid = topics.thread_id(key)
            mark = tid if tid else "— (não criado)"
            print(f"  {key:10} → {title}  {mark}")

    @app.command()
    def reset() -> None:
        """Limpa os thread_ids salvos (não apaga os tópicos no Telegram)."""
        from src.core.use_cases.telegram_topics import TelegramTopics

        TelegramTopics().reset()
        print("Mapa de tópicos limpo. Rode 'setup' para recriar/remapear.")
