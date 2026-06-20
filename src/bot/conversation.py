from pathlib import Path
from typing import Callable

from src.config.settings import logger


class ConversationFlow:
    """Stateful multi-step dialogs (connect form + resume upload).

    Holds the ``_step``/``_form`` machine that was previously inlined in the
    bot. Sends prompts via the injected client and hands finished forms to
    the :class:`BrowserTaskRunner`.
    """

    def __init__(self, client, runner) -> None:
        self.client = client
        self.runner = runner
        self._form: dict = {}
        self._step: str = ""

    @property
    def active(self) -> bool:
        return bool(self._step)

    def reset(self) -> None:
        self._form = {}
        self._step = ""

    # ── Entry points ──────────────────────────────────────────────────────────

    def start_connect(self) -> None:
        self._form = {}
        self._step = "connect_url"
        self.client.send("🔗 <b>Novo Connect</b>\n\nQual a URL da busca de pessoas?")

    def start_resume(self) -> None:
        self._step = "awaiting_resume"
        self.client.send("📄 Envie o arquivo do currículo (PDF ou TXT).")

    # ── Inline button callbacks ───────────────────────────────────────────────

    def handle_callback(self, data: str) -> None:
        if data.startswith("sp:"):  # start_page escolhido
            value = data[3:]
            if value == "custom":
                self._step = "connect_start_page_custom"
                self.client.send("Digite a página inicial:")
                return
            self._form["start_page"] = int(value)
            self._ask_max_pages()

        elif data.startswith("mp:"):  # max_pages escolhido
            value = data[3:]
            if value == "custom":
                self._step = "connect_max_pages_custom"
                self.client.send("Digite o máximo de páginas:")
                return
            self._form["max_pages"] = int(value)
            self._step = ""
            self._launch_connect()

    def _ask_start_page(self) -> None:
        self._step = "connect_start_page"
        self.client.send(
            "A partir de qual página?",
            buttons=[
                [
                    {"text": "1", "data": "sp:1"},
                    {"text": "10", "data": "sp:10"},
                    {"text": "25", "data": "sp:25"},
                    {"text": "50", "data": "sp:50"},
                ],
                [{"text": "✏️ Digitar", "data": "sp:custom"}],
            ],
        )

    def _ask_max_pages(self) -> None:
        self._step = "connect_max_pages"
        self.client.send(
            "Máximo de páginas?",
            buttons=[
                [
                    {"text": "25", "data": "mp:25"},
                    {"text": "50", "data": "mp:50"},
                    {"text": "100", "data": "mp:100"},
                ],
                [{"text": "✏️ Digitar", "data": "mp:custom"}],
            ],
        )

    # ── Text input mid-form ───────────────────────────────────────────────────

    def handle_text(self, text: str, on_command: Callable[[str], None]) -> None:
        if text.startswith("/"):
            self.reset()
            on_command(text)
            return

        if self._step == "connect_url":
            self._form["url"] = text.strip()
            self._ask_start_page()

        elif self._step == "connect_start_page_custom":
            try:
                self._form["start_page"] = int(text.strip())
            except ValueError:
                self.client.send("❌ Digite um número válido.")
                return
            self._ask_max_pages()

        elif self._step == "connect_max_pages_custom":
            try:
                self._form["max_pages"] = int(text.strip())
            except ValueError:
                self.client.send("❌ Digite um número válido.")
                return
            self._step = ""
            self._launch_connect()

    def _launch_connect(self) -> None:
        if self.runner.is_busy():
            self.client.send("⚠️ Já tem uma tarefa rodando. Use /stop primeiro.")
            self.reset()
            return
        url = self._form["url"]
        start_page = self._form.get("start_page", 1)
        max_pages = self._form.get("max_pages", 100)
        self._form = {}
        self.runner.launch_connect(url, start_page, max_pages)

    # ── Document (resume upload) ───────────────────────────────────────────────

    def handle_document(self, doc: dict) -> None:
        if self._step != "awaiting_resume":
            return

        name = doc.get("file_name", "")
        if not (name.endswith(".pdf") or name.endswith(".txt")):
            self.client.send("❌ Envie o currículo em PDF ou TXT.")
            return

        try:
            content = self.client.download_file(doc["file_id"])
            dest = Path(".local") / "files" / name
            dest.write_bytes(content)
            self.runner.set_resume(str(dest))
            self._step = ""
            self.client.send(f"✅ Currículo definido: <code>{dest.name}</code>")
            logger.info(f"Resume updated: {dest}")
        except Exception as e:
            self._step = ""
            self.client.send("❌ Erro ao salvar o currículo.")
            logger.error(f"Failed to save resume: {e}")
