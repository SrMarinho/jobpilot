import threading
import os
import sys
import time
from pathlib import Path
import requests
from src.config.settings import logger


def _find_resume(hint: str = "resume.txt") -> str:
    """Return hint if it exists, otherwise find first .pdf or .txt in files/ or cwd."""
    if Path(hint).exists():
        return hint
    for directory in (Path("files"), Path(".")):
        for ext in ("*.pdf", "*.txt"):
            found = list(directory.glob(ext))
            if found:
                return str(found[0])
    return hint  # fallback, will raise at read time with a clear error


class TelegramBot:
    def __init__(self, driver_factory, resume_path: str = "resume.txt"):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = str(os.getenv("TELEGRAM_CHAT_ID"))
        self.admin_id = str(os.getenv("TELEGRAM_ADMIN_ID", os.getenv("TELEGRAM_CHAT_ID")))
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.offset = 0
        self.driver_factory = driver_factory
        self.resume_path = _find_resume(resume_path)
        logger.info(f"Resume: {self.resume_path}")
        self.stop_event = threading.Event()
        self.current_task: threading.Thread | None = None

        self._form: dict = {}
        self._step: str = ""

    # ── Telegram API ──────────────────────────────────────────────────────────

    def send(self, text: str, buttons: list | None = None) -> None:
        payload: dict = {
            "chat_id": self.admin_id,
            "text": text,
            "parse_mode": "HTML",
        }
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

    def send_notification(self, text: str) -> None:
        try:
            requests.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

    def _answer_callback(self, callback_query_id: str) -> None:
        try:
            requests.post(
                f"{self.base_url}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id},
                timeout=10,
            )
        except Exception:
            pass

    def _get_updates(self) -> list:
        try:
            resp = requests.get(
                f"{self.base_url}/getUpdates",
                params={
                    "offset": self.offset,
                    "timeout": 30,
                    "allowed_updates": ["message", "callback_query"],
                },
                timeout=35,
            )
            return resp.json().get("result", [])
        except Exception:
            return []

    def _handle_document(self, doc: dict) -> None:
        if self._step != "awaiting_resume":
            return

        name = doc.get("file_name", "")
        if not (name.endswith(".pdf") or name.endswith(".txt")):
            self.send("❌ Envie o currículo em PDF ou TXT.")
            return

        try:
            file_info = requests.get(
                f"{self.base_url}/getFile",
                params={"file_id": doc["file_id"]},
                timeout=10,
            ).json()["result"]
            file_path = file_info["file_path"]
            content = requests.get(
                f"https://api.telegram.org/file/bot{self.token}/{file_path}",
                timeout=30,
            ).content
            dest = Path("files") / name
            dest.write_bytes(content)
            self.resume_path = str(dest)
            self._step = ""
            self.send(f"✅ Currículo definido: <code>{dest.name}</code>")
            logger.info(f"Resume updated: {dest}")
        except Exception as e:
            self._step = ""
            self.send("❌ Erro ao salvar o currículo.")
            logger.error(f"Failed to save resume: {e}")

    # ── Command handling ──────────────────────────────────────────────────────

    def _handle(self, text: str) -> None:
        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/help":
            self.send(
                "📋 <b>Comandos disponíveis:</b>\n\n"
                "/connect — enviar conexões\n"
                "/apply &lt;url&gt; — aplicar vagas\n"
                "/resume — atualizar currículo\n"
                "/status — ver se tem tarefa rodando\n"
                "/stop — parar tarefa atual\n"
                "/ping — verificar se o bot está vivo\n"
                "/reiniciar — reiniciar o bot"
            )

        elif cmd == "/status":
            if self.current_task and self.current_task.is_alive():
                self.send("⚙️ Tarefa em andamento...")
            else:
                self.send("💤 Nenhuma tarefa rodando.")

        elif cmd == "/stop":
            if self.current_task and self.current_task.is_alive():
                self.stop_event.set()
                self.send("🛑 Sinal de parada enviado...")
            else:
                self.send("Nenhuma tarefa ativa.")

        elif cmd == "/connect":
            self._form = {}
            self._step = "connect_url"
            self.send("🔗 <b>Novo Connect</b>\n\nQual a URL da busca de pessoas?")

        elif cmd == "/ping":
            start = time.time()
            self.send(f"🏓 Pong! <code>{(time.time() - start) * 1000:.0f}ms</code>")

        elif cmd == "/reiniciar":
            self.send("🔄 Reiniciando...")
            logger.info("Restart requested via Telegram")
            os.execv(sys.executable, [sys.executable] + sys.argv)

        elif cmd == "/resume":
            self._step = "awaiting_resume"
            self.send("📄 Envie o arquivo do currículo (PDF ou TXT).")

        elif cmd == "/apply":
            if not arg:
                self.send("Uso: /apply &lt;url&gt;")
                return
            self._launch_apply(arg)

        else:
            self.send("Comando não reconhecido. Digite /help.")

    # ── Inline button callbacks ───────────────────────────────────────────────

    def _handle_callback(self, data: str) -> None:
        if data.startswith("sp:"):        # start_page escolhido
            value = data[3:]
            if value == "custom":
                self._step = "connect_start_page_custom"
                self.send("Digite a página inicial:")
                return
            self._form["start_page"] = int(value)
            self._ask_max_pages()

        elif data.startswith("mp:"):      # max_pages escolhido
            value = data[3:]
            if value == "custom":
                self._step = "connect_max_pages_custom"
                self.send("Digite o máximo de páginas:")
                return
            self._form["max_pages"] = int(value)
            self._step = ""
            self._launch_connect()

    def _ask_start_page(self) -> None:
        self._step = "connect_start_page"
        self.send(
            "A partir de qual página?",
            buttons=[
                [
                    {"text": "1",  "data": "sp:1"},
                    {"text": "10", "data": "sp:10"},
                    {"text": "25", "data": "sp:25"},
                    {"text": "50", "data": "sp:50"},
                ],
                [{"text": "✏️ Digitar", "data": "sp:custom"}],
            ],
        )

    def _ask_max_pages(self) -> None:
        self._step = "connect_max_pages"
        self.send(
            "Máximo de páginas?",
            buttons=[
                [
                    {"text": "25",  "data": "mp:25"},
                    {"text": "50",  "data": "mp:50"},
                    {"text": "100", "data": "mp:100"},
                ],
                [{"text": "✏️ Digitar", "data": "mp:custom"}],
            ],
        )

    # ── Text input mid-form ───────────────────────────────────────────────────

    def _handle_form_text(self, text: str) -> None:
        if text.startswith("/"):
            self._form = {}
            self._step = ""
            self._handle(text)
            return

        if self._step == "connect_url":
            self._form["url"] = text.strip()
            self._ask_start_page()

        elif self._step == "connect_start_page_custom":
            try:
                self._form["start_page"] = int(text.strip())
            except ValueError:
                self.send("❌ Digite um número válido.")
                return
            self._ask_max_pages()

        elif self._step == "connect_max_pages_custom":
            try:
                self._form["max_pages"] = int(text.strip())
            except ValueError:
                self.send("❌ Digite um número válido.")
                return
            self._step = ""
            self._launch_connect()

    # ── Task launchers ────────────────────────────────────────────────────────

    def _launch_connect(self) -> None:
        if self.current_task and self.current_task.is_alive():
            self.send("⚠️ Já tem uma tarefa rodando. Use /stop primeiro.")
            return
        url = self._form["url"]
        start_page = self._form.get("start_page", 1)
        max_pages = self._form.get("max_pages", 100)
        self._form = {}
        self.stop_event.clear()
        self.send(f"🔗 Iniciando conexões a partir da página {start_page} (máx: {max_pages})...")
        self.current_task = threading.Thread(
            target=self._run_connect, args=(url, start_page, max_pages), daemon=True
        )
        self.current_task.start()

    def _launch_apply(self, url: str) -> None:
        if self.current_task and self.current_task.is_alive():
            self.send("⚠️ Já tem uma tarefa rodando. Use /stop primeiro.")
            return
        self.stop_event.clear()
        self.send("📋 Iniciando candidaturas...")
        self.current_task = threading.Thread(target=self._run_apply, args=(url,), daemon=True)
        self.current_task.start()

    # ── Task runners ──────────────────────────────────────────────────────────

    def _run_connect(self, url: str, start_page: int = 1, max_pages: int = 100) -> None:
        from src.automation.tasks.connection_manager import ConnectionManager
        driver = self.driver_factory()
        manager = None
        try:
            manager = ConnectionManager(driver, url=url, start_page=start_page, max_pages=max_pages, stop_event=self.stop_event)
            manager.run()
        except Exception as e:
            self.send("❌ Erro ao executar conexões.")
            logger.error(f"connect task error: {e}")
        finally:
            sent = manager.connect_people.invite_sended if manager else 0
            self.send(f"🔗 Conexões finalizadas! Total enviado: {sent}")
            try:
                driver.quit()
            except Exception:
                pass

    def _run_apply(self, url: str) -> None:
        from src.automation.tasks.job_application_manager import JobApplicationManager
        driver = self.driver_factory()
        try:
            manager = JobApplicationManager(driver, url=url, resume_path=self.resume_path, stop_event=self.stop_event)
            manager.run()
            self.send(
                f"✅ Candidaturas concluídas!\n"
                f"Avaliadas: {manager.evaluated_count} | Aplicadas: {manager.applied_count}"
            )
        except Exception as e:
            self.send(f"❌ Erro: {e}")
            logger.error(f"apply task error: {e}")
        finally:
            try:
                driver.quit()
            except Exception:
                pass

    # ── Polling loop ──────────────────────────────────────────────────────────

    def _register_commands(self) -> None:
        try:
            requests.post(
                f"{self.base_url}/setMyCommands",
                json={"commands": [
                    {"command": "connect",   "description": "Enviar conexões"},
                    {"command": "apply",     "description": "Aplicar vagas — /apply <url>"},
                    {"command": "resume",    "description": "Atualizar currículo"},
                    {"command": "status",    "description": "Ver se tem tarefa rodando"},
                    {"command": "stop",      "description": "Parar tarefa atual"},
                    {"command": "ping",      "description": "Verificar se o bot está vivo"},
                    {"command": "reiniciar", "description": "Reiniciar o bot"},
                    {"command": "help",      "description": "Ver todos os comandos"},
                ]},
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"Failed to register commands: {e}")

    def run(self) -> None:
        self._register_commands()
        self.send("🤖 <b>JobPilot online!</b> Digite /help para ver os comandos.")
        logger.info("Telegram bot polling started")
        while True:
            updates = self._get_updates()
            for update in updates:
                self.offset = update["update_id"] + 1

                # callback de botão inline
                if "callback_query" in update:
                    cq = update["callback_query"]
                    if str(cq["from"]["id"]) == self.admin_id:
                        self._answer_callback(cq["id"])
                        self._handle_callback(cq["data"])
                    continue

                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "")
                if chat_id != self.admin_id:
                    continue

                if "document" in msg:
                    self._handle_document(msg["document"])
                    continue

                if not text:
                    continue

                if self._step:
                    self._handle_form_text(text)
                elif text.startswith("/"):
                    self._handle(text)
