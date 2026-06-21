from pathlib import Path
from typing import Callable

from src.config.settings import logger


def _record(feature: str, event: str, **kw) -> None:
    try:
        from src.core.use_cases.events_tracker import record_event

        record_event(feature, event, **kw)
    except Exception:
        pass


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

    def handle_callback(self, data: str, message: dict | None = None) -> None:
        if data.startswith("autopost_"):
            self._handle_autopost_callback(data, message)
            return

        if data.startswith("followup_"):
            self._handle_followup_callback(data)
            return

        if data.startswith("engage_"):
            self._handle_engage_callback(data)
            return

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

    # ── Autopost approval ─────────────────────────────────────────────────────

    def _handle_autopost_callback(self, data: str, message: dict | None = None) -> None:
        from src.core.use_cases.posted_tracker import (
            PostedTracker,
            STATUS_APPROVED,
            STATUS_REJECTED,
        )

        action, _, draft_id = data.partition(":")
        tracker = PostedTracker()
        draft = tracker.get_draft(draft_id)
        if not draft or draft.get("status") != "pending":
            self.client.send("⚠️ Draft expirado ou já processado.")
            return

        # Remove os botões da mensagem original (evita toque duplo).
        if message and action != "autopost_edit":
            self.client.edit_reply_markup(
                message.get("chat", {}).get("id"), message.get("message_id")
            )

        if action == "autopost_approve":
            tracker.set_status(draft_id, STATUS_APPROVED)
            _record("autopost", "approved", key=draft_id, detail="telegram")
            self.client.send(
                "✅ Aprovado. Será publicado no próximo horário de publicação."
            )

        elif action == "autopost_reject":
            tracker.set_status(draft_id, STATUS_REJECTED)
            _record("autopost", "rejected", key=draft_id, detail="telegram")
            self.client.send("❌ Draft rejeitado.")

        elif action == "autopost_regen":
            tracker.set_status(draft_id, STATUS_REJECTED)
            self.client.send("🔄 Regenerando draft...")
            self.runner.launch_autopost_generate(
                source=draft.get("source"),
                topic=draft.get("topic"),
                fmt=draft.get("format"),
            )

        elif action == "autopost_edit":
            self._step = "autopost_edit"
            self._form = {"draft_id": draft_id}
            self.client.send("✏️ Envie o novo texto do post:")

    # ── Engage comment approval (human-in-loop) ───────────────────────────────

    def _handle_engage_callback(self, data: str) -> None:
        action, _, req_id = data.partition(":")
        gate = self.runner.approval
        if not gate.has(req_id):
            self.client.send("⚠️ Aprovação expirada ou já processada.")
            return
        if action == "engage_approve":
            gate.resolve(req_id, "approve")
            self.client.send("✅ Comentário aprovado.")
        elif action == "engage_reject":
            gate.resolve(req_id, "reject")
            self.client.send("❌ Comentário pulado.")
        elif action == "engage_edit":
            self._step = "engage_edit"
            self._form = {"req_id": req_id}
            self.client.send("✏️ Envie o novo texto do comentário:")

    def _handle_engage_edit(self, text: str) -> None:
        req_id = self._form.get("req_id")
        self.reset()
        gate = self.runner.approval
        if gate.resolve(req_id, "approve", text.strip()):
            self.client.send("✅ Comentário editado e aprovado.")
        else:
            self.client.send("⚠️ Aprovação expirada.")

    # ── Follow-up DM approval ─────────────────────────────────────────────────

    def _handle_followup_callback(self, data: str) -> None:
        from src.core.use_cases.followup_tracker import (
            FollowupTracker,
            STATUS_REJECTED,
        )

        action, _, draft_id = data.partition(":")
        tracker = FollowupTracker()
        draft = tracker.get_draft(draft_id)
        if not draft or draft.get("status") != "pending":
            self.client.send("⚠️ DM expirado ou já processado.")
            return

        if action == "followup_approve":
            self.client.send("📤 Enviando DM no LinkedIn...")
            self.runner.launch_followup_send(draft_id)

        elif action == "followup_reject":
            tracker.set_status(draft_id, STATUS_REJECTED)
            self.client.send("❌ DM descartado.")

        elif action == "followup_regen":
            self.client.send("🔄 Regenere via /followup (novo scan).")

        elif action == "followup_edit":
            self._step = "followup_edit"
            self._form = {"draft_id": draft_id}
            self.client.send("✏️ Envie o novo texto do DM:")

    def _handle_followup_edit(self, text: str) -> None:
        from src.core.use_cases.followup_dm import validate_dm
        from src.core.use_cases.followup_tracker import FollowupTracker
        from src.automation.tasks.followup_manager import followup_buttons

        draft_id = self._form.get("draft_id")
        self.reset()
        ok, payload = validate_dm(text)
        if not ok:
            self.client.send(f"❌ Texto inválido ({payload}). Edição cancelada.")
            return
        tracker = FollowupTracker()
        draft = tracker.update_content(draft_id, payload)
        if not draft:
            self.client.send("⚠️ Draft não encontrado.")
            return
        header = f"💬 <b>DM editado</b> — {draft.get('name')}\n\n"
        self.client.send(header + payload, buttons=followup_buttons(draft_id))

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

        if self._step == "autopost_edit":
            self._handle_autopost_edit(text)
            return

        if self._step == "followup_edit":
            self._handle_followup_edit(text)
            return

        if self._step == "engage_edit":
            self._handle_engage_edit(text)
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

    def _handle_autopost_edit(self, text: str) -> None:
        from src.core.use_cases.post_drafter import validate_draft
        from src.core.use_cases.posted_tracker import PostedTracker
        from src.interfaces.cli.autopost.logic import _approval_buttons

        draft_id = self._form.get("draft_id")
        self.reset()
        ok, payload = validate_draft(text)
        if not ok:
            self.client.send(f"❌ Texto inválido ({payload}). Edição cancelada.")
            return
        tracker = PostedTracker()
        draft = tracker.update_content(draft_id, payload)
        if not draft:
            self.client.send("⚠️ Draft não encontrado.")
            return
        header = f"📝 <b>Autopost draft (editado)</b>\n<i>{len(payload)} chars</i>\n\n"
        self.client.send(header + payload, buttons=_approval_buttons(draft_id))

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
