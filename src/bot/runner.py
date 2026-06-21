import os
import threading

from playwright.async_api import async_playwright

from src.config.settings import logger
from src.interfaces.cli.browser import (
    create_context,
    acquire_browser_lock,
    _release_browser_lock,
)
from src.utils.async_utils import run_async
from src.automation.tasks.connection_manager import ConnectionManager
from src.automation.tasks.job_application_manager import create_application_manager


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
        if self.is_busy():
            self.client.send("⚠️ Já tem uma tarefa rodando. Use /stop primeiro.")
            return
        self.client.send(
            f"🔗 Iniciando conexões a partir da página {start_page} (máx: {max_pages})..."
        )
        self._spawn(lambda: self._connect_async(url, start_page, max_pages))

    def launch_apply(self, url: str) -> None:
        if self.is_busy():
            self.client.send("⚠️ Já tem uma tarefa rodando. Use /stop primeiro.")
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
            "user_name": os.getenv("USER_NAME", "Matheus Marinho"),
            "user_headline": os.getenv(
                "USER_HEADLINE", "Software Engineer focado em Python e Node.js"
            ),
        }
        from src.interfaces.cli.autopost.logic import run_autopost

        self._spawn_detached(lambda: run_autopost(cfg))

    def launch_engage(self, max_posts: int = 3, review: bool = True) -> None:
        if self.is_busy():
            self.client.send("⚠️ Já tem uma tarefa rodando. Use /stop primeiro.")
            return
        mode = "com aprovação" if review else "automático"
        self.client.send(f"🤝 Iniciando engage ({mode})...")
        self._spawn(lambda: self._engage_async(max_posts, review))

    def launch_followup_scan(self, max_dms: int = 5) -> None:
        if self.is_busy():
            self.client.send("⚠️ Já tem uma tarefa rodando. Use /stop primeiro.")
            return
        self.client.send("💬 Buscando conexões novas p/ follow-up...")
        self._spawn(lambda: self._followup_scan_async(max_dms))

    def launch_followup_send(self, draft_id: str) -> None:
        if self.is_busy():
            self.client.send("⚠️ Já tem uma tarefa rodando. Use /stop primeiro.")
            return
        self._spawn(lambda: self._followup_send_async(draft_id))

    # ── Coroutines ────────────────────────────────────────────────────────────

    async def _connect_async(
        self, url: str, start_page: int = 1, max_pages: int = 100
    ) -> None:
        lock = await acquire_browser_lock("bot_connect")
        try:
            async with async_playwright() as pw:
                context, page = await create_context(pw, force_headless=False)
                manager = None
                try:
                    manager = ConnectionManager(
                        page,
                        url=url,
                        start_page=start_page,
                        max_pages=max_pages,
                        stop_event=self.stop_event,
                    )
                    await manager.run()
                except Exception as e:
                    self.client.send("❌ Erro ao executar conexões.")
                    logger.error(f"connect task error: {e}")
                finally:
                    sent = manager.connect_people.invite_sended if manager else 0
                    self.client.send(f"🔗 Conexões finalizadas! Total enviado: {sent}")
                    try:
                        await context.close()
                    except Exception:
                        pass
        finally:
            _release_browser_lock(lock, "bot_connect")

    async def _apply_async(self, url: str) -> None:
        lock = await acquire_browser_lock("bot_apply")
        try:
            async with async_playwright() as pw:
                context, page = await create_context(pw, force_headless=False)
                try:
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
                except Exception as e:
                    self.client.send(f"❌ Erro: {e}")
                    logger.error(f"apply task error: {e}")
                finally:
                    try:
                        await context.close()
                    except Exception:
                        pass
        finally:
            _release_browser_lock(lock, "bot_apply")

    async def _engage_async(self, max_posts: int, review: bool) -> None:
        import os

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

        lock = await acquire_browser_lock("bot_engage")
        try:
            async with async_playwright() as pw:
                context, page = await create_context(pw, force_headless=False)
                try:
                    manager = EngagementManager(
                        page,
                        llm_provider=provider,
                        resume_path=self.resume_path,
                        user_name=os.getenv("USER_NAME", "Matheus Marinho"),
                        user_headline=os.getenv(
                            "USER_HEADLINE",
                            "Software Engineer focado em Python e Node.js",
                        ),
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
                except Exception as e:
                    self.client.send(f"❌ Erro no engage: {e}")
                    logger.error(f"engage task error: {e}")
                finally:
                    try:
                        await context.close()
                    except Exception:
                        pass
        finally:
            _release_browser_lock(lock, "bot_engage")

    async def _followup_scan_async(self, max_dms: int) -> None:
        from src.interfaces.cli.followup.logic import (
            resolve_followup_config,
            run_followup_browser,
        )

        cfg = resolve_followup_config(None, max_dms, scheduled=False, force=False)
        lock = await acquire_browser_lock("bot_followup")
        try:
            async with async_playwright() as pw:
                context, page = await create_context(pw, force_headless=False)
                try:
                    await run_followup_browser(page, cfg)
                except Exception as e:
                    self.client.send(f"❌ Erro no follow-up: {e}")
                    logger.error(f"followup scan error: {e}")
                finally:
                    try:
                        await context.close()
                    except Exception:
                        pass
        finally:
            _release_browser_lock(lock, "bot_followup")

    async def _followup_send_async(self, draft_id: str) -> None:
        from src.core.use_cases.followup_tracker import FollowupTracker
        from src.automation.pages.messaging_page import MessagingPage

        tracker = FollowupTracker()
        draft = tracker.get_draft(draft_id)
        if not draft:
            self.client.send("⚠️ Draft de DM não encontrado.")
            return

        lock = await acquire_browser_lock("bot_followup_send")
        try:
            async with async_playwright() as pw:
                context, page = await create_context(pw, force_headless=False)
                try:
                    ok = await MessagingPage(page).send_dm(
                        draft["profile_url"], draft["content"]
                    )
                    if ok:
                        tracker.mark_sent(draft_id)
                        self.client.send(f"✅ DM enviado p/ {draft.get('name')}!")
                    else:
                        self.client.send("❌ Falha ao enviar o DM.")
                except Exception as e:
                    self.client.send(f"❌ Erro ao enviar DM: {e}")
                    logger.error(f"followup send error: {e}")
                finally:
                    try:
                        await context.close()
                    except Exception:
                        pass
        finally:
            _release_browser_lock(lock, "bot_followup_send")

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
