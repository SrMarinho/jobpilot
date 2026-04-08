import threading
import os
import requests
from src.config.settings import logger


class TelegramBot:
    def __init__(self, driver_factory, resume_path: str = "resume.txt"):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = str(os.getenv("TELEGRAM_CHAT_ID"))       # canal — notificações
        self.admin_id = str(os.getenv("TELEGRAM_ADMIN_ID", os.getenv("TELEGRAM_CHAT_ID")))  # usuário — comandos
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.offset = 0
        self.driver_factory = driver_factory
        self.resume_path = resume_path
        self.stop_event = threading.Event()
        self.current_task: threading.Thread | None = None

        # form state
        self._form: dict = {}   # current form data being collected
        self._step: str = ""    # current step name

    # ── Telegram API ─────────────────────────────────────────────────────────

    def send(self, text: str, to_admin: bool = True) -> None:
        chat = self.admin_id if to_admin else self.chat_id
        try:
            requests.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": chat, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"Failed to send Telegram message: {e}")

    def _get_updates(self) -> list:
        try:
            resp = requests.get(
                f"{self.base_url}/getUpdates",
                params={"offset": self.offset, "timeout": 30, "allowed_updates": ["message"]},
                timeout=35,
            )
            return resp.json().get("result", [])
        except Exception:
            return []

    # ── Command handling ──────────────────────────────────────────────────────

    def _handle(self, text: str) -> None:
        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd == "/help":
            self.send(
                "📋 <b>Comandos disponíveis:</b>\n\n"
                "/connect &lt;url&gt; — enviar conexões\n"
                "/apply &lt;url&gt; — aplicar vagas\n"
                "/status — ver se tem tarefa rodando\n"
                "/stop — parar tarefa atual"
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
            self._start_connect_form()

        elif cmd == "/apply":
            if not arg:
                self.send("Uso: /apply &lt;url&gt;")
                return
            self._start_task("apply", arg)

        else:
            self.send("Comando não reconhecido. Digite /help.")

    # ── Form (step-by-step) ───────────────────────────────────────────────────

    def _start_connect_form(self) -> None:
        self._form = {}
        self._step = "connect_url"
        self.send("🔗 <b>Novo Connect</b>\n\nQual a URL da busca de pessoas?")

    def _handle_form(self, text: str) -> None:
        if text.startswith("/"):
            self._form = {}
            self._step = ""
            self._handle(text)
            return

        if self._step == "connect_url":
            self._form["url"] = text.strip()
            self._step = "connect_start_page"
            self.send("A partir de qual página? <i>(padrão: 1 — responda com o número ou <b>pular</b>)</i>")

        elif self._step == "connect_start_page":
            if text.strip().lower() == "pular":
                self._form["start_page"] = 1
            else:
                try:
                    self._form["start_page"] = int(text.strip())
                except ValueError:
                    self.send("❌ Digite um número ou <b>pular</b>.")
                    return
            self._step = "connect_max_pages"
            self.send("Máximo de páginas? <i>(padrão: 100 — responda com o número ou <b>pular</b>)</i>")

        elif self._step == "connect_max_pages":
            if text.strip().lower() == "pular":
                self._form["max_pages"] = 100
            else:
                try:
                    self._form["max_pages"] = int(text.strip())
                except ValueError:
                    self.send("❌ Digite um número ou <b>pular</b>.")
                    return
            self._step = ""
            self._launch_connect()

    def _launch_connect(self) -> None:
        if self.current_task and self.current_task.is_alive():
            self.send("⚠️ Já tem uma tarefa rodando. Use /stop primeiro.")
            return
        url = self._form["url"]
        start_page = self._form["start_page"]
        max_pages = self._form["max_pages"]
        self._form = {}
        self.stop_event.clear()
        self.send(f"🔗 Iniciando conexões a partir da página {start_page} (máx: {max_pages})...")
        self.current_task = threading.Thread(
            target=self._run_connect, args=(url, start_page, max_pages), daemon=True
        )
        self.current_task.start()

    def _start_task(self, task: str, arg: str) -> None:
        if self.current_task and self.current_task.is_alive():
            self.send("⚠️ Já tem uma tarefa rodando. Use /stop primeiro.")
            return
        self.stop_event.clear()
        self.send("📋 Iniciando candidaturas...")
        self.current_task = threading.Thread(target=self._run_apply, args=(arg,), daemon=True)
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
                    {"command": "connect", "description": "Enviar conexões — /connect <url>"},
                    {"command": "apply",   "description": "Aplicar vagas — /apply <url>"},
                    {"command": "status",  "description": "Ver se tem tarefa rodando"},
                    {"command": "stop",    "description": "Parar tarefa atual"},
                    {"command": "help",    "description": "Ver todos os comandos"},
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
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "")
                if chat_id != self.admin_id:
                    continue
                if self._step:
                    self._handle_form(text)
                elif text.startswith("/"):
                    self._handle(text)
