import os
import sys
import time

from src.config.settings import logger


class UpdateRouter:
    """Dispatches slash commands to the runner / conversation.

    Pure routing: no HTTP, no browser. Stateless commands (help/status/
    stop/ping/reiniciar) resolve here; stateful ones delegate to the
    :class:`ConversationFlow`; task launches go to the :class:`BrowserTaskRunner`.
    """

    def __init__(self, client, runner, conversation) -> None:
        self.client = client
        self.runner = runner
        self.conversation = conversation

    def handle_command(self, text: str) -> None:
        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/help":
            self.client.send(
                "📋 <b>Comandos disponíveis:</b>\n\n"
                "/connect — enviar conexões\n"
                "/apply &lt;url&gt; — aplicar vagas\n"
                "/autopost — gerar post autoral\n"
                "/autopost_topic &lt;tema&gt; — post com tema custom\n"
                "/autopost_format &lt;tipo&gt; — força formato\n"
                "/autopost_list — últimos posts + pendentes\n"
                "/resume — atualizar currículo\n"
                "/status — ver se tem tarefa rodando\n"
                "/stop — parar tarefa atual\n"
                "/ping — verificar se o bot está vivo\n"
                "/reiniciar — reiniciar o bot"
            )

        elif cmd == "/status":
            if self.runner.is_busy():
                self.client.send("⚙️ Tarefa em andamento...")
            else:
                self.client.send("💤 Nenhuma tarefa rodando.")

        elif cmd == "/stop":
            if self.runner.is_busy():
                self.runner.stop()
                self.client.send("🛑 Sinal de parada enviado...")
            else:
                self.client.send("Nenhuma tarefa ativa.")

        elif cmd == "/connect":
            self.conversation.start_connect()

        elif cmd == "/autopost":
            self.client.send("📝 Gerando autopost draft...")
            self.runner.launch_autopost_generate()

        elif cmd == "/autopost_topic":
            if not arg:
                self.client.send("Uso: /autopost_topic &lt;tema&gt;")
                return
            self.client.send("📝 Gerando autopost draft (tema custom)...")
            self.runner.launch_autopost_generate(source="manual", topic=arg)

        elif cmd == "/autopost_format":
            if not arg:
                self.client.send(
                    "Uso: /autopost_format &lt;snippet|story|dissertativo|contrarian&gt;"
                )
                return
            self.client.send(f"📝 Gerando autopost draft (formato {arg})...")
            self.runner.launch_autopost_generate(fmt=arg)

        elif cmd == "/autopost_list":
            self._autopost_list()

        elif cmd == "/ping":
            start = time.time()
            self.client.send(
                f"🏓 Pong! <code>{(time.time() - start) * 1000:.0f}ms</code>"
            )

        elif cmd == "/reiniciar":
            self.client.send("🔄 Reiniciando...")
            logger.info("Restart requested via Telegram")
            os.execv(sys.executable, [sys.executable] + sys.argv)

        elif cmd == "/resume":
            self.conversation.start_resume()

        elif cmd == "/apply":
            if not arg:
                self.client.send("Uso: /apply &lt;url&gt;")
                return
            self.runner.launch_apply(arg)

        else:
            self.client.send("Comando não reconhecido. Digite /help.")

    def _autopost_list(self) -> None:
        from src.core.use_cases.posted_tracker import PostedTracker

        tracker = PostedTracker()
        posts = tracker._data.get("posts", [])[-5:]
        pending = tracker.pending_drafts()
        lines = ["📝 <b>Autopost</b>\n"]
        if posts:
            lines.append("<b>Últimos publicados:</b>")
            for p in reversed(posts):
                day = p.get("day", "?")
                topic = (p.get("topic") or "")[:40]
                lines.append(f"• {day} — {topic}")
        else:
            lines.append("<i>Nenhum post publicado ainda.</i>")
        if pending:
            lines.append(f"\n<b>Drafts pendentes:</b> {len(pending)}")
        self.client.send("\n".join(lines))
