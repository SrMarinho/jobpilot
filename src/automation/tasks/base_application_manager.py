import time
import asyncio
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.common.by import By
from src.core.use_cases.job_evaluator import JobEvaluator, _LEVEL_KEYWORDS, _normalize
from src.core.use_cases.skills_tracker import track_missing_skills
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
    eval_result: tuple | None = None  # (is_match, salary, reason, missing, contract)
    state: str = "pending"  # pending|extracted|filtered|evaluating|approved|rejected|applying|applied|failed
    note: str = ""


class BaseJobApplicationManager(ABC):
    """Shared pipeline: page loop, dedupe, evaluator, qa-driven handler.

    Pipeline (per page):
      1. extract  — sequential, walks each card, opens, reads title/desc, runs cheap filters.
      2. eval     — concurrent (asyncio.gather, semaphore = eval_concurrency).
      3. apply    — sequential (single Selenium driver), submits each approved job.

    Subclass per site overrides hooks for site-specific quirks.
    Shared bits (form_answers.json cache, tracker, evaluator, skills, telegram) stay here.
    """
    site: str = "unknown"
    PAGE_SIZE: int = 25

    def __init__(
        self,
        driver: WebDriver,
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
        self.driver = driver
        self.base_url = self._normalize_url(url)
        self.max_pages = max_pages
        self.start_page = start_page
        self.on_page_change = on_page_change
        self.no_submit = no_submit
        self.eval_concurrency = max(1, min(eval_concurrency, self.PAGE_SIZE))
        self.on_update = on_update or (lambda _item: None)

        self.page = self._build_page(driver, self.base_url)
        self.evaluator = JobEvaluator(resume_path, preferences=preferences, level=level)
        self.tracker = AppliedJobsTracker()
        self.stop_event = stop_event or threading.Event()
        self.max_applications = max_applications
        self.applied_count = 0
        self.evaluated_count = 0
        self.handler = self._build_handler(driver, resume=self.evaluator.resume)

    # ── site hooks ────────────────────────────────────────────────────────────

    def _normalize_url(self, url: str) -> str:
        return url

    @abstractmethod
    def _build_page(self, driver, url): ...

    @abstractmethod
    def _build_handler(self, driver, resume: str): ...

    @abstractmethod
    def _next_page_url(self, page_num: int) -> str: ...

    @abstractmethod
    def _get_card_id(self, card) -> str: ...

    @abstractmethod
    def _get_card_job_url(self, card, page_num: int, idx: int) -> str | None: ...

    @abstractmethod
    def _get_apply_btn(self): ...

    @abstractmethod
    def _submit_application(self, salary, title: str, description: str) -> bool: ...

    def _relocate_card(self, item: JobItem) -> bool:
        """Re-open job (apply phase). Default: re-find by card_id in current card list.
        Subclasses can override to navigate by URL when stale."""
        try:
            cards = self.page.get_job_cards()
            for c in cards:
                if self._get_card_id(c) == item.card_id:
                    self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", c)
                    time.sleep(0.3)
                    try:
                        c.click()
                    except Exception:
                        self.driver.execute_script("arguments[0].click();", c)
                    time.sleep(1.5)
                    return True
        except Exception as e:
            logger.debug(f"_relocate_card failed: {e}")
        return False

    # ── pipeline ──────────────────────────────────────────────────────────────

    def run(self):
        logger.info(f"Site detected: {self.site}")
        logger.info(f"Eval concurrency: {self.eval_concurrency} (max page = {self.PAGE_SIZE})")
        seen_page_ids: list[frozenset] = []
        for page_num in range(self.start_page, self.start_page + self.max_pages):
            if self.stop_event.is_set():
                logger.info("Stop requested, halting job application manager")
                break

            if self.on_page_change:
                self.on_page_change(page_num)
            url = self._next_page_url(page_num)
            logger.info(f"Navigating to page {page_num}")
            self.driver.get(url)

            job_cards = self._wait_for_job_cards(page_num)
            if not job_cards:
                logger.info("No more jobs found, stopping")
                break

            current_ids = frozenset(self._get_card_id(c) for c in job_cards)
            if seen_page_ids and current_ids and current_ids == seen_page_ids[-1]:
                logger.info("Page identical to previous — no more unique jobs, stopping")
                break
            seen_page_ids = seen_page_ids[-1:] + [current_ids]

            logger.info(f"Found {len(job_cards)} jobs on page {page_num}")
            self._process_jobs(job_cards, page_num)

        logger.info(f"Finished. Evaluated: {self.evaluated_count} | Applied: {self.applied_count}")

    def _wait_for_job_cards(self, page_num: int) -> list:
        time.sleep(1.5)
        try:
            WebDriverWait(self.driver, 5).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except Exception:
            pass

        loading_selectors = [
            "div.loader", "div.artdeco-loader", "[class*=loader]",
            "[class*=spinner]", "[class*=skeleton]", "[class*=ghost]",
        ]
        try:
            WebDriverWait(self.driver, 8).until_not(
                lambda d: any(
                    e.is_displayed()
                    for sel in loading_selectors
                    for e in d.find_elements(By.CSS_SELECTOR, sel)
                )
            )
        except Exception:
            pass

        max_attempts = 5 if page_num > 1 else 3
        for attempt in range(max_attempts):
            cards = self.page.get_job_cards()
            if cards:
                return cards
            if attempt < max_attempts - 1:
                logger.debug(f"No job cards yet on page {page_num}, retrying ({attempt + 1}/{max_attempts})...")
                time.sleep(2)
        return []

    def _process_jobs(self, job_cards, page_num: int = 1):
        items = self._extract_jobs(job_cards, page_num)
        if not items:
            return
        approved = self._eval_jobs(items)
        if approved:
            self._apply_jobs(approved)

    # Phase 1: extract + cheap filters (sequential, drives browser)
    def _extract_jobs(self, job_cards, page_num: int) -> list[JobItem]:
        items: list[JobItem] = []
        count = len(job_cards)
        for i in range(count):
            if self.stop_event.is_set():
                break
            try:
                cards = self.page.get_job_cards()
                if i >= len(cards):
                    break
                card = cards[i]
                if hasattr(self.page, "close_modal"):
                    self.page.close_modal()
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
                time.sleep(0.3)

                job_url = self._get_card_job_url(card, page_num, i)
                card_id = self._get_card_id(card)

                try:
                    card.click()
                except Exception:
                    self.driver.execute_script("arguments[0].click();", card)
                time.sleep(1.5)

                title = self.page.get_job_title() or ""
                description = self.page.get_job_description()
                company = self.page.get_company_name() if hasattr(self.page, "get_company_name") else ""

                if not title or not description:
                    logger.info(f"Job {i + 1}: Could not extract details, skipping")
                    continue

                if not job_url:
                    job_url = self.driver.current_url

                item = JobItem(
                    idx=i + 1, title=title, description=description, company=company,
                    job_url=job_url, card_id=card_id, state="extracted",
                )
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

    # Phase 2: eval concurrent
    def _eval_jobs(self, items: list[JobItem]) -> list[JobItem]:
        async def _eval_one(item: JobItem, sem: asyncio.Semaphore):
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
                    track_missing_skills(missing)
                if is_match:
                    item.state = "approved"
                    item.note = reason
                else:
                    item.state = "rejected"
                    item.note = reason
                    self.tracker.mark_rejected(item.job_url, item.title, reason=reason, site=self.site)
                self.on_update(item)

        async def _eval_all():
            sem = asyncio.Semaphore(self.eval_concurrency)
            await asyncio.gather(*(_eval_one(it, sem) for it in items))

        logger.info(f"Evaluating {len(items)} jobs (concurrency={self.eval_concurrency})...")
        asyncio.run(_eval_all())
        self.evaluated_count += len(items)
        approved = [i for i in items if i.state == "approved"]
        logger.info(f"Approved: {len(approved)}/{len(items)}")
        return approved

    # Phase 3: apply sequential
    def _apply_jobs(self, approved: list[JobItem]):
        for item in approved:
            if self.stop_event.is_set():
                logger.info("Stop requested, halting apply phase")
                return
            if self.max_applications and self.applied_count >= self.max_applications:
                logger.info(f"Reached max applications limit ({self.max_applications}), stopping")
                self.stop_event.set()
                return
            try:
                item.state = "applying"
                self.on_update(item)

                if not self._relocate_card(item):
                    logger.warning(f"Could not relocate card for '{item.title}', skipping")
                    item.state = "failed"
                    item.note = "relocate failed"
                    self.on_update(item)
                    continue

                apply_btn = self._get_apply_btn()
                if not apply_btn:
                    skip_reason = getattr(self, "_last_skip_reason", None)
                    if skip_reason:
                        self.tracker.mark_rejected(item.job_url, item.title, reason=skip_reason, site=self.site)
                        item.state = "rejected"
                        item.note = skip_reason
                        logger.info(f"Job '{item.title}': {skip_reason}")
                    else:
                        item.state = "failed"
                        item.note = "no apply button"
                        logger.info(f"Job '{item.title}': No apply button, skipping")
                    self.on_update(item)
                    continue

                logger.info(f"Applying to '{item.title}'")
                apply_btn.click()
                time.sleep(1.5)

                _, salary, _, _, contract = item.eval_result
                success = self._submit_application(salary, item.title, item.description)
                if success:
                    self.applied_count += 1
                    detected_level = detect_level(item.title, item.description)
                    self.tracker.mark_applied(
                        item.job_url, item.title, salary,
                        company=item.company, level=detected_level,
                        site=self.site, contract=contract,
                    )
                    item.state = "applied"
                    self.on_update(item)
                    logger.info(f"Applied ({self.applied_count} total)")
                else:
                    item.state = "failed"
                    item.note = "submit failed"
                    self.on_update(item)
                time.sleep(1)
            except Exception as e:
                logger.error(f"Error applying '{item.title}': {e}")
                item.state = "failed"
                item.note = str(e)[:60]
                self.on_update(item)
