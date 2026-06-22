"""Human-in-loop gate para ações geradas por IA (engage).

O EngagementManager roda numa thread do runner com seu próprio event loop; o
polling do Telegram roda na thread principal. O gate liga os dois: a tarefa
pede aprovação (manda botões e dá ``await`` num poll), e o callback do
Telegram (thread principal) resolve a decisão num dict thread-safe.

Decisões: approve (usa o texto), reject (pula), edit (espera novo texto). Sem
resposta dentro do timeout → trata como reject pra não travar o run.
"""

import asyncio
import threading
import uuid

from src.config.settings import logger


class ApprovalGate:
    def __init__(self, client, timeout_s: int = 600, poll_s: float = 1.0):
        self.client = client
        self.timeout_s = timeout_s
        self.poll_s = poll_s
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}

    def _buttons(self, req_id: str) -> list:
        return [
            [
                {"text": "✅ Postar", "data": f"engage_approve:{req_id}"},
                {"text": "❌ Pular", "data": f"engage_reject:{req_id}"},
            ],
            [{"text": "✏️ Editar", "data": f"engage_edit:{req_id}"}],
        ]

    async def request(self, kind: str, text: str, author: str) -> str | None:
        """Manda preview + botões e espera a decisão. Retorna texto ou None."""
        req_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._pending[req_id] = {"decision": None, "text": text}
        header = f"🤝 <b>Aprovar {kind}?</b>\n<i>post de {author[:60]}</i>\n\n"
        self.client.send(header + text, buttons=self._buttons(req_id), topic="engage")

        waited = 0.0
        while waited < self.timeout_s:
            await asyncio.sleep(self.poll_s)
            waited += self.poll_s
            with self._lock:
                entry = self._pending.get(req_id, {})
                decision = entry.get("decision")
            if decision is None:
                continue
            with self._lock:
                final = self._pending.pop(req_id, {}).get("text")
            if decision == "approve":
                return final
            return None  # reject

        with self._lock:
            self._pending.pop(req_id, None)
        logger.info(f"Aprovação {req_id} expirou; tratando como reject")
        self.client.send("⏰ Sem resposta — comentário pulado.", topic="engage")
        return None

    # ── Resolvido pelo callback do Telegram (thread principal) ────────────────

    def has(self, req_id: str) -> bool:
        with self._lock:
            return req_id in self._pending

    def resolve(self, req_id: str, decision: str, text: str | None = None) -> bool:
        with self._lock:
            entry = self._pending.get(req_id)
            if not entry:
                return False
            entry["decision"] = decision
            if text is not None:
                entry["text"] = text
        return True
