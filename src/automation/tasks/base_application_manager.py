import asyncio
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable
from playwright.async_api import Page
from src.core.use_cases.job_evaluator import JobEvaluator, _LEVEL_KEYWORDS, _normalize
from src.core.use_cases.skills_tracker import track_missing_skills_async
from src.core.use_cases.applied_jobs_tracker import AppliedJobsTracker
from src.config.settings import logger


def detect_level(title: str, description: str = "") -> str:
    text = _normalize(f"{title} {description[:500]}")
    for level, keywords in _LEVEL_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return level
    return "unknown"


@dataclass
class JobItem:
    idx: int
    title: str = ""
    description: str = ""
    company: str = ""
    job_url: str = ""
    card_id: str = ""
    eval_result: tuple | None = None
    state: str = "pending"
    note: str = ""


class BaseJobApplicationManager(ABC):
    site: str = "unknown"
    PAGE_SIZE: int = 25

    def __init__(
        self,
        page: Page,
        url: str,
        resume_path: str,
        preferences: str = "",
        level: str = "",
        max_pages: int = 100,
        max_applications: int = 0,
        start_page: int = 1,
        stop_event: threading.Event | None = None,
        on_page_change=None,
        no_submit: bool = False,
        eval_concurrency: int = 1,
        on_update: Callable[[JobItem], None] | None = None,
    ):
        self.page = page
        self.base_url = self._normalize_url(url)
        self.max_pages = max_pages
        self.start_page = start_page
        self.on_page_change = on_page_change
        self.no_submit = no_submit
        self.eval_concurrency = max(1, min(eval_concurrency, self.PAGE_SIZE))
        self.on_update = on_update or (lambda _item: None)

        self.page_obj = self._build_page(page, self.base_url)
        self.evaluator = JobEvaluator(resume_path, preferences=preferences, level=level)
        self.tracker = AppliedJobsTracker()
        self.stop_event = stop_event or threading.Event()
        self.max_applications = max_applications
        self.applied_count = 0
        self.evaluated_count = 0
        self.handler = self._build_handler(page, resume=self.evaluator.resume)

    # ── site hooks ────────────────────────────────────────────────────────────

    def _normalize_url(self, url: str) -> str:
        return url

    @abstractmethod
    def _build_page(self, page, url): ...

    @abstractmethod
    def _build_handler(self, page, resume: str): ...

    @abstractmethod
    def _next_page_url(self, page_num: int) -> str: ...

    @abstractmethod
    async def _get_card_id(self, card) -> str: ...

    @abstractmethod
    async def _get_card_job_url(self, card, page_num: int, idx: int) -> str | None: ...

    @abstractmethod
    async def _get_apply_btn(self): ...

    @abstractmethod
    async def _submit_application(self, salary, title: str, description: str) -> bool: ...

    # ── overlap pipeline ──────────────────────────────────────────────────────

    async def run(self):
        logger.info(f"Site detected: {self.site}")
        logger.info(f"Eval concurrency: {self.eval_concurrency} (max page = {self.PAGE_SIZE})")

        eval_queue: asyncio.Queue[JobItem | None] = asyncio.Queue()
        apply_queue: asyncio.Queue[JobItem | None] = asyncio.Queue()

        extract_task = asyncio.create_task(self._extract_all(eval_queue))
        eval_task = asyncio.create_task(self._evaluate_all(eval_queue, apply_queue))
        apply_task = asyncio.create_task(self._apply_all(apply_queue))

        await asyncio.gather(extract_task, eval_task, apply_task)

        logger.info(f"Finished. Evaluated: {self.evaluated_count} | Applied: {self.applied_count}")

    async def _extract_all(self, eval_queue: asyncio.Queue):
        seen_page_ids: list[frozenset] = []
        for page_num in range(self.start_page, self.start_page + self.max_pages):
            if self.stop_event.is_set():
                break
            if self.on_page_change:
                self.on_page_change(page_num)
            url = self._next_page_url(page_num)
            logger.info(f"Navigating to page {page_num}")
            await self.page.goto(url, wait_until="domcontentloaded")

            job_cards = await self._wait_for_job_cards(page_num)
            if not job_cards:
                logger.info("No more jobs found, stopping")
                break

            current_ids = frozenset(await asyncio.gather(*[self._get_card_id(c) for c in job_cards]))
            if seen_page_ids and current_ids and current_ids == seen_page_ids[-1]:
                logger.info("Page identical to previous — no more unique jobs, stopping")
                break
            seen_page_ids = seen_page_ids[-1:] + [current_ids]

            logger.info(f"Found {len(job_cards)} jobs on page {page_num}")
            items = await self._extract_jobs(job_cards, page_num)
            for item in items:
                await eval_queue.put(item)

        await eval_queue.put(None)

    async def _evaluate_all(self, eval_queue: asyncio.Queue, apply_queue: asyncio.Queue):
        sem = asyncio.Semaphore(self.eval_concurrency)
        tasks: set[asyncio.Task] = set()

        async def _eval_one(item: JobItem):
            async with sem:
                if self.stop_event.is_set():
                    return
                item.state = "evaluating"
                self.on_update(item)
                try:
                    result = await self.evaluator.evaluate_async(item.title, item.description)
                except Exception as e:
                    logger.error(f"Eval error '{item.title}': {e}")
                    item.state = "failed"
                    item.note = f"eval error: {e}"
                    self.on_update(item)
                    return
                item.eval_result = result
                is_match, salary, reason, missing, contract = result
                if missing:
                    await track_missing_skills_async(missing)
                if is_match:
                    item.state = "approved"
                    item.note = reason
                    self.on_update(item)
                    await apply_queue.put(item)
                else:
                    item.state = "rejected"
                    item.note = reason
                    self.tracker.mark_rejected(item.job_url, item.title, reason=reason, site=self.site)
                    self.on_update(item)
                self.evaluated_count += 1

        while True:
            item = await eval_queue.get()
            eval_queue.task_done()
            if item is None:
                break
            t = asyncio.create_task(_eval_one(item))
            tasks.add(t)
            t.add_done_callback(tasks.discard)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        apply_queue.put_nowait(None)

    async def _apply_all(self, apply_queue: asyncio.Queue):
        while True:
            item = await apply_queue.get()
            if item is None:
                apply_queue.task_done()
                break
            if self.stop_event.is_set():
                apply_queue.task_done()
                continue
            if self.max_applications and self.applied_count >= self.max_applications:
                logger.info(f"Reached max applications limit ({self.max_applications}), stopping")
                self.stop_event.set()
                apply_queue.task_done()
                continue
            await self._apply_one(item)
            apply_queue.task_done()

    async def _apply_one(self, item: JobItem):
        apply_page = await self.page.context.new_page()
        item.state = "applying"
        self.on_update(item)
        try:
            await apply_page.goto(item.job_url, wait_until="domcontentloaded")
            await apply_page.wait_for_timeout(2000)

            temp_page_obj = self._build_page(apply_page, item.job_url)
            temp_handler = self._build_handler(apply_page, resume=self.evaluator.resume)

            if hasattr(temp_page_obj, 'get_easy_apply_btn'):
                btn = await temp_page_obj.get_easy_apply_btn()
            elif hasattr(temp_page_obj, 'get_apply_btn'):
                btn = await temp_page_obj.get_apply_btn()
            else:
                btn = None

            if not btn:
                skip_reason = getattr(self, "_last_skip_reason", None)
                if skip_reason:
                    self.tracker.mark_rejected(item.job_url, item.title, reason=skip_reason, site=self.site)
                    item.state = "rejected"
                    item.note = skip_reason
                else:
                    item.state = "failed"
                    item.note = "no apply button"
                self.on_update(item)
                return

            await btn.click()
            await apply_page.wait_for_timeout(1500)

            _, salary, _, _, contract = item.eval_result
            if hasattr(temp_handler, 'submit_easy_apply'):
                success = await temp_handler.submit_easy_apply(salary, item.title, item.description, no_submit=self.no_submit)
            elif hasattr(temp_handler, 'submit'):
                success = await temp_handler.submit(salary_expectation=salary, no_submit=self.no_submit)
            else:
                success = False

            if success:
                self.applied_count += 1
                lvl = detect_level(item.title, item.description)
                self.tracker.mark_applied(item.job_url, item.title, salary, company=item.company, level=lvl, site=self.site, contract=contract)
                item.state = "applied"
                self.on_update(item)
                logger.info(f"Applied ({self.applied_count} total)")
            else:
                item.state = "failed"
                item.note = "submit failed"
                self.on_update(item)
        except Exception as e:
            logger.error(f"Error applying '{item.title}': {e}")
            item.state = "failed"
            item.note = str(e)[:60]
            self.on_update(item)
        finally:
            try:
                await apply_page.close()
            except Exception:
                pass

    # ── shared helpers ────────────────────────────────────────────────────────

    async def _wait_for_job_cards(self, page_num: int) -> list:
        await self.page.wait_for_timeout(1500)
        try:
            await self.page.wait_for_function("document.readyState === 'complete'", timeout=5000)
        except Exception:
            pass

        loading_selectors = [
            "div.loader", "div.artdeco-loader", "[class*=loader]",
            "[class*=spinner]", "[class*=skeleton]", "[class*=ghost]",
        ]
        try:
            for sel in loading_selectors:
                loader = self.page.locator(sel)
                if await loader.is_visible(timeout=2000):
                    await loader.wait_for(state="hidden", timeout=8000)
        except Exception:
            pass

        max_attempts = 5 if page_num > 1 else 3
        for attempt in range(max_attempts):
            cards = await self.page_obj.get_job_cards()
            if cards:
                return cards
            if attempt < max_attempts - 1:
                logger.debug(f"No job cards yet on page {page_num}, retrying ({attempt + 1}/{max_attempts})...")
                await self.page.wait_for_timeout(2000)
        return []

    async def _extract_jobs(self, job_cards, page_num: int) -> list[JobItem]:
        items: list[JobItem] = []
        count = len(job_cards)
        for i in range(count):
            if self.stop_event.is_set():
                break
            try:
                cards = await self.page_obj.get_job_cards()
                if i >= len(cards):
                    break
                card = cards[i]
                if hasattr(self.page_obj, "close_modal"):
                    await self.page_obj.close_modal()
                await card.scroll_into_view_if_needed()
                await self.page.wait_for_timeout(300)

                job_url = await self._get_card_job_url(card, page_num, i)
                card_id = await self._get_card_id(card)

                try:
                    await card.click()
                except Exception:
                    await self.page.evaluate("(el) => el.click()", card)
                await self.page.wait_for_timeout(1500)

                title = await self.page_obj.get_job_title() or ""
                description = await self.page_obj.get_job_description()
                company = await self.page_obj.get_company_name() if hasattr(self.page_obj, "get_company_name") else ""

                if not title or not description:
                    logger.info(f"Job {i + 1}: Could not extract details, skipping")
                    continue

                if not job_url:
                    job_url = self.page.url

                item = JobItem(idx=i + 1, title=title, description=description, company=company, job_url=job_url, card_id=card_id, state="extracted")
                self.on_update(item)

                if self.tracker.already_applied(job_url):
                    item.state = "rejected"
                    item.note = "already applied"
                    self.on_update(item)
                    logger.info(f"Job {i + 1}: Already applied to '{title}', skipping")
                    continue
                if self.tracker.already_rejected(job_url):
                    item.state = "rejected"
                    item.note = "already rejected"
                    self.on_update(item)
                    logger.info(f"Job {i + 1}: Already rejected '{title}', skipping")
                    continue

                if self.evaluator.tech_reject(title, description):
                    self.tracker.mark_rejected(job_url, title, reason="Quick reject: tech stack mismatch", site=self.site)
                    item.state = "rejected"
                    item.note = "tech mismatch"
                    self.on_update(item)
                    continue

                items.append(item)
            except Exception as e:
                logger.error(f"Error extracting job {i + 1}: {e}")
        logger.info(f"Extracted {len(items)} candidates for evaluation")
        return items
