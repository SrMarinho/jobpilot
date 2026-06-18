import threading
from dataclasses import dataclass, field

from playwright.async_api import Page

from src.automation.pages import FeedPage
from src.core.ai.llm_provider import LLMProvider
from src.core.use_cases.engagement_handler import (
    EngagementHandler,
    is_blacklisted,
    load_resume_text,
)
from src.core.use_cases.engaged_posts_tracker import EngagedPostsTracker
from src.config.settings import logger


@dataclass
class EngagementResult:
    liked: int = 0
    commented: int = 0
    shared: int = 0
    skipped: int = 0
    engaged_urns: list[str] = field(default_factory=list)


class EngagementManager:
    def __init__(
        self,
        page: Page,
        llm_provider: LLMProvider,
        resume_path: str,
        user_name: str = "",
        user_headline: str = "",
        max_posts: int = 3,
        enable_like: bool = True,
        enable_comment: bool = True,
        enable_share: bool = True,
        dry_run: bool = False,
        stop_event: threading.Event | None = None,
    ):
        self.page = page
        self.max_posts = max_posts
        self.enable_like = enable_like
        self.enable_comment = enable_comment
        self.enable_share = enable_share
        self.dry_run = dry_run
        self.stop_event = stop_event or threading.Event()

        self.feed = FeedPage(page)
        self.tracker = EngagedPostsTracker()
        self.handler = EngagementHandler(
            llm_provider,
            resume_text=load_resume_text(resume_path),
            user_name=user_name,
            user_headline=user_headline,
        )
        self.result = EngagementResult()
        self.self_author = self.tracker.self_author() or user_name or ""

    async def _collect_candidates(self, target: int) -> list[tuple]:
        """Scroll until we have `target` relevant posts (or hit scroll cap)."""
        candidates: list[tuple] = []  # (post_handle, urn, author, text)
        scrolls_done = 0
        max_scrolls = 8
        seen_urns: set[str] = set()

        await self.feed.scroll_feed(n=3, pause_ms=1500)
        scrolls_done += 3

        while len(candidates) < target and scrolls_done <= max_scrolls:
            posts = await self.feed.get_posts()
            for post in posts:
                if self.stop_event.is_set():
                    break
                urn = await self.feed.get_post_urn(post)
                if not urn or urn in seen_urns:
                    continue
                seen_urns.add(urn)

                if self.tracker.already_engaged(urn):
                    self.result.skipped += 1
                    continue
                author = await self.feed.get_post_author(post)
                if (
                    self.self_author
                    and author.strip().lower() == self.self_author.strip().lower()
                ):
                    self.result.skipped += 1
                    continue
                text = await self.feed.get_post_text(post)
                if not text or len(text) < 30:
                    self.result.skipped += 1
                    continue
                if is_blacklisted(text):
                    self.result.skipped += 1
                    continue
                logger.info(f"Evaluating relevance for author={author!r}")
                if not await self.handler.is_relevant(text):
                    self.result.skipped += 1
                    continue
                candidates.append((post, urn, author, text))
                logger.info(f"Selected candidate {len(candidates)}/{target}: {author}")
                if len(candidates) >= target:
                    break

            if len(candidates) >= target:
                break
            await self.feed.scroll_feed(n=2, pause_ms=1500)
            scrolls_done += 2

        return candidates[:target]

    async def run(self) -> EngagementResult:
        await self.feed.goto()
        candidates = await self._collect_candidates(self.max_posts)
        if not candidates:
            logger.warning("No relevant posts found on feed")
            return self.result
        if len(candidates) < self.max_posts:
            logger.warning(
                f"Only {len(candidates)} relevant posts found (target {self.max_posts})"
            )

        for i, (post, urn, author, text) in enumerate(candidates, 1):
            if self.stop_event.is_set():
                break
            logger.info(f"=== Post {i}/{len(candidates)} — {author} ===")
            actions: list[str] = []
            comment_text = ""

            if self.dry_run:
                logger.info(f"[dry-run] Would like, comment, share for urn={urn}")
                preview = await self.handler.generate_comment(text, author)
                if preview:
                    logger.info(f"[dry-run] Generated comment: {preview!r}")
                    comment_text = preview
                    actions = ["like", "comment", "share"]
                else:
                    actions = ["like", "share"]
                self.tracker.mark_engaged(urn, author, actions, comment_text)
                self.result.liked += 1
                if "comment" in actions:
                    self.result.commented += 1
                self.result.shared += 1
                continue

            if self.enable_like:
                if await self.feed.like_post(post):
                    actions.append("like")
                    self.result.liked += 1
                await self.feed.random_pause(5, 12)

            if self.enable_comment:
                comment = await self.handler.generate_comment(text, author)
                if comment:
                    if await self.feed.submit_comment(post, comment):
                        actions.append("comment")
                        comment_text = comment
                        self.result.commented += 1
                    await self.feed.random_pause(5, 12)

            if self.enable_share:
                if await self.feed.share_post(post):
                    actions.append("share")
                    self.result.shared += 1
                await self.feed.random_pause(5, 10)

            if actions:
                self.tracker.mark_engaged(urn, author, actions, comment_text)
                self.result.engaged_urns.append(urn)
            else:
                logger.warning(f"No actions taken for urn={urn}")

            if i < len(candidates):
                await self.feed.random_pause(30, 60)

        logger.info(
            f"Engagement done. Liked: {self.result.liked} | "
            f"Commented: {self.result.commented} | Shared: {self.result.shared}"
        )
        return self.result
