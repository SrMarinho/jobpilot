import os
import threading
from typing import Awaitable, Callable

from playwright.async_api import Page, async_playwright

from src.automation.checkpoint import CheckpointError
from src.config import sections as settings_sections
from src.config.settings import logger
from src.core.use_cases.rate_limiter import RateLimiter
from src.core.use_cases.run_guard import check_run
from src.interfaces.cli.browser import (
    create_context,
    acquire_browser_lock,
    _release_browser_lock,
)
from src.utils.async_utils import run_async
from src.automation.tasks.connection_manager import ConnectionManager
from src.automation.tasks.job_application_manager import create_application_manager

CHECKPOINT_MSG = (
    "🚧 <b>Checkpoint do LinkedIn</b> — a automação parou p/ não arriscar "
    "bloqueio.\nAbra o Chrome e resolva a verificação manualmente."
)


class BrowserTaskRunner:
    """Owns the single background browser task and its lifecycle.

    Only one task runs at a time. Each task opens Chrome under the
    app-level browser lock (serialized with the CLI runs) and reports
    progress through the injected :class:`TelegramClient`.
    """

    def __init__(self, client, resume_path: str) -> None:
        self.client = client
        self.resume_path = resume_path
        self.stop_event = threading.Event()
        self.current_task: threading.Thread | None = None
        from src.bot.approval import ApprovalGate

        self.approval = ApprovalGate(client)

    # ── State ─────────────────────────────────────────────────────────────────

    def is_busy(self) -> bool:
        return bool(self.current_task and self.current_task.is_alive())

    def _blocked(self, action: str) -> bool:
        """Recusa a tarefa se o guard barrar, avisando o motivo no Telegram.

        O bot passa pelas mesmas barreiras da CLI: até aqui um /connect pelo
        Telegram furava a quota inteira, porque os guards só rodavam com
        --scheduled.
        """
        if self.is_busy():
            self.client.send("⚠️ Já tem uma tarefa rodando. Use /stop primeiro.")
            return True
        verdict = check_run(action)
        if not verdict:
            self.client.send(f"🚫 <b>{action}</b> bloqueado — {verdict.reason}")
            logger.info(f"Bot recusou {action}: {verdict.reason}")
            return True
        return False

    def stop(self) -> None:
        self.stop_event.set()

    def set_resume(self, path: str) -> None:
        self.resume_path = path

    def _spawn(self, coro_factory) -> None:
        self.stop_event.clear()
        self.current_task = threading.Thread(
            target=lambda: run_async(coro_factory()), daemon=True
        )
        self.current_task.start()

    def _spawn_detached(self, coro_factory) -> None:
        """Fire-and-forget thread for non-browser work (draft generation)."""
        threading.Thread(target=lambda: run_async(coro_factory()), daemon=True).start()

    # ── Launchers ─────────────────────────────────────────────────────────────

    def launch_connect(
        self, url: str, start_page: int = 1, max_pages: int = 100
    ) -> None:
        if self._blocked("connect"):
            return
        self.client.send(
            f"🔗 Iniciando conexões a partir da página {start_page} (máx: {max_pages})..."
        )
        self._spawn(lambda: self._connect_async(url, start_page, max_pages))

    def launch_apply(self, url: str) -> None:
        if self._blocked("apply"):
            return
        self.client.send("📋 Iniciando candidaturas...")
        self._spawn(lambda: self._apply_async(url))

    def launch_autopost_generate(
        self,
        source: str | None = None,
        topic: str | None = None,
        fmt: str | None = None,
    ) -> None:
        """Generate a draft off the browser path (LLM only) and send to Telegram."""
        cfg = {
            "resume_path": self.resume_path,
            "source": source,
            "topic": topic,
            "format": fmt,
            "dry_run": False,
            "no_telegram": False,
            **settings_sections.user.as_dict(),
        }
        from src.interfaces.cli.autopost.logic import run_autopost

        self._spawn_detached(lambda: run_autopost(cfg))

    def launch_engage(self, max_posts: int = 3, review: bool = True) -> None:
        if self._blocked("engage"):
            return
        mode = "com aprovação" if review else "automático"
        self.client.send(f"🤝 Iniciando engage ({mode})...")
        self._spawn(lambda: self._engage_async(max_posts, review))

    def launch_followup_scan(self, max_dms: int = 5) -> None:
        if self._blocked("dm"):
            return
        self.client.send("💬 Buscando conexões novas p/ follow-up...")
        self._spawn(lambda: self._followup_scan_async(max_dms))

    def launch_followup_send(self, draft_id: str) -> None:
        if self._blocked("dm"):
            return
        self._spawn(lambda: self._followup_send_async(draft_id))

    # ── Browser scaffolding ───────────────────────────────────────────────────

    async def _with_browser(
        self,
        label: str,
        work: Callable[[Page], Awaitable[None]],
        *,
        error_prefix: str,
        on_finish: Callable[[], None] | None = None,
    ) -> None:
        """Roda ``work(page)`` sob o browser lock, com Chrome e erros tratados.

        Único ponto do bot que abre browser: garante lock adquirido/liberado,
        contexto sempre fechado, ``CheckpointError`` reportado como tal (e não
        como crash genérico) e traceback completo no log.
        """
        lock = await acquire_browser_lock(label)
        try:
            async with async_playwright() as pw:
                context, page = await create_context(pw, force_headless=False)
                try:
                    await work(page)
                except CheckpointError as e:
                    # Checkpoint é sinal forte: insistir é o pior movimento.
                    # Bloqueia os runs até liberação manual.
                    RateLimiter().open_cooldown(f"checkpoint durante {label}")
                    self.client.send(f"{CHECKPOINT_MSG}\n<code>{e}</code>")
                    logger.error(f"{label}: checkpoint detectado — {e}")
                except Exception as e:
                    self.client.send(f"{error_prefix}: {e}")
                    logger.exception(f"{label} task error")
                finally:
                    if on_finish:
                        on_finish()
                    try:
                        await context.close()
                    except Exception:
                        pass
        finally:
            _release_browser_lock(lock, label)

    # ── Coroutines ────────────────────────────────────────────────────────────

    async def _connect_async(
        self, url: str, start_page: int = 1, max_pages: int = 100
    ) -> None:
        managers: list[ConnectionManager] = []

        async def work(page: Page) -> None:
            manager = ConnectionManager(
                page,
                url=url,
                start_page=start_page,
                max_pages=max_pages,
                stop_event=self.stop_event,
            )
            managers.append(manager)
            await manager.run()

        def report() -> None:
            sent = managers[0].connect_people.invite_sended if managers else 0
            self.client.send(f"🔗 Conexões finalizadas! Total enviado: {sent}")

        await self._with_browser(
            "bot_connect",
            work,
            error_prefix="❌ Erro ao executar conexões",
            on_finish=report,
        )

    async def _apply_async(self, url: str) -> None:
        async def work(page: Page) -> None:
            manager = create_application_manager(
                page,
                url=url,
                resume_path=self.resume_path,
                stop_event=self.stop_event,
            )
            await manager.run()
            self.client.send(
                f"✅ Candidaturas concluídas!\n"
                f"Avaliadas: {manager.evaluated_count} | Aplicadas: {manager.applied_count}"
            )

        await self._with_browser("bot_apply", work, error_prefix="❌ Erro")

    async def _engage_async(self, max_posts: int, review: bool) -> None:
        from src.core.ai.llm_provider import get_eval_provider
        from src.core.ai.warmup import warmup_llm_providers
        from src.automation.tasks.engagement_manager import EngagementManager
        from src.core.use_cases.engage_targets import load_targets

        os.environ.setdefault("LLM_PROVIDER_EVAL", "langchain")
        warmup_llm_providers()
        provider = get_eval_provider()

        approver = None
        if review:

            async def approver(text, author):
                return await self.approval.request("comentário", text, author)

        async def work(page: Page) -> None:
            manager = EngagementManager(
                page,
                llm_provider=provider,
                resume_path=self.resume_path,
                **settings_sections.user.as_dict(),
                max_posts=max_posts,
                stop_event=self.stop_event,
                targets=load_targets(),
                comment_approver=approver,
            )
            result = await manager.run()
            self.client.send(
                f"🤝 Engage concluído!\n"
                f"❤️ {result.liked} | 💬 {result.commented} | 🔁 {result.shared}"
            )

        await self._with_browser("bot_engage", work, error_prefix="❌ Erro no engage")

    async def _followup_scan_async(self, max_dms: int) -> None:
        from src.interfaces.cli.followup.logic import (
            resolve_followup_config,
            run_followup_browser,
        )

        cfg = resolve_followup_config(None, max_dms, scheduled=False, force=False)

        async def work(page: Page) -> None:
            await run_followup_browser(page, cfg)

        await self._with_browser(
            "bot_followup", work, error_prefix="❌ Erro no follow-up"
        )

    async def _followup_send_async(self, draft_id: str) -> None:
        from src.core.use_cases.followup_tracker import FollowupTracker
        from src.automation.pages.messaging_page import MessagingPage

        tracker = FollowupTracker()
        draft = tracker.get_draft(draft_id)
        if not draft:
            self.client.send("⚠️ Draft de DM não encontrado.")
            return

        async def work(page: Page) -> None:
            ok = await MessagingPage(page).send_dm(
                draft["profile_url"], draft["content"]
            )
            if ok:
                tracker.mark_sent(draft_id)
                self.client.send(f"✅ DM enviado p/ {draft.get('name')}!")
            else:
                self.client.send("❌ Falha ao enviar o DM.")

        await self._with_browser(
            "bot_followup_send", work, error_prefix="❌ Erro ao enviar DM"
        )

    async def _capture_ssi(self, page) -> None:
        """Best-effort SSI snapshot after publishing (never fatal)."""
        try:
            from src.automation.pages.ssi_page import SSIPage
            from src.core.use_cases.ssi_tracker import SSITracker

            tracker = SSITracker()
            if tracker.already_captured_today():
                return
            snap = await SSIPage(page).scrape_with_goto()
            if snap:
                tracker.save(snap)
                logger.info(f"SSI captured: total={snap['total']}/100")
        except Exception as e:
            logger.warning(f"SSI capture failed (non-fatal): {e}")
