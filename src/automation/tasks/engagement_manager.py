import threading
from dataclasses import dataclass, field

from playwright.async_api import Page

from src.automation.pages import FeedPage
from src.core.ai.llm_provider import LLMProvider
from src.core.use_cases.engagement_handler import EngagementHandler
from src.core.use_cases.content_filters import is_blacklisted
from src.core.use_cases.resume_loader import load_resume_text
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
        targets: list[str] | None = None,
        comment_approver=None,
    ):
        self.page = page
        self.max_posts = max_posts
        self.enable_like = enable_like
        self.enable_comment = enable_comment
        self.enable_share = enable_share
        self.dry_run = dry_run
        self.stop_event = stop_event or threading.Event()
        self.targets = targets or []
        # Async callable (text, author) -> approved_text | None. Quando setado,
        # o comentário passa por aprovação humana antes de postar (Telegram).
        self.comment_approver = comment_approver

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

    async def _select(self, post, seen_urns: set[str]):
        """Filtra um post. Retorna (urn, author, text) se deve engajar, ``None``
        se pular (filtrado), ou ``"dup"`` se já visto (não conta como novo)."""
        urn = await self.feed.get_post_urn(post)
        if not urn or urn in seen_urns:
            return "dup"
        seen_urns.add(urn)

        if self.tracker.already_engaged(urn):
            self.result.skipped += 1
            return None
        author = await self.feed.get_post_author(post)
        if (
            self.self_author
            and author.strip().lower() == self.self_author.strip().lower()
        ):
            self.result.skipped += 1
            return None
        text = await self.feed.get_post_text(post)
        if not text or len(text) < 30:
            self.result.skipped += 1
            return None
        if is_blacklisted(text):
            self.result.skipped += 1
            return None
        if self.targets:
            from src.core.use_cases.engage_targets import matches_target

            if not matches_target(author, text, self.targets):
                self.result.skipped += 1
                return None
        if not await self.handler.is_relevant(text):
            self.result.skipped += 1
            return None
        return (urn, author, text)

    async def _engage_post(self, post, urn: str, author: str, text: str) -> bool:
        """Like/comment/share num post. Retorna True se alguma ação ocorreu."""
        actions: list[str] = []
        comment_text = ""
        variant = ""

        if self.dry_run:
            preview, variant = await self.handler.generate_comment(text, author)
            if preview:
                logger.info(f"[dry-run] Generated comment ({variant}): {preview!r}")
                comment_text = preview
                actions = ["like", "comment", "share"]
            else:
                actions = ["like", "share"]
            self.tracker.mark_engaged(urn, author, actions, comment_text, variant)
            self.result.liked += 1
            if "comment" in actions:
                self.result.commented += 1
            self.result.shared += 1
            return True

        if self.enable_like:
            if await self.feed.like_post(post):
                actions.append("like")
                self.result.liked += 1
            await self.feed.random_pause(5, 12)

        if self.enable_comment:
            comment, variant = await self.handler.generate_comment(text, author)
            if comment and self.comment_approver:
                comment = await self.comment_approver(comment, author)
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

        await self.feed.dismiss_overlays()

        if actions:
            self.tracker.mark_engaged(urn, author, actions, comment_text, variant)
            self.result.engaged_urns.append(urn)
            return True
        logger.warning(f"No actions taken for urn={urn}")
        return False

    async def run(self) -> EngagementResult:
        """Engaja ATÉ atingir ``max_posts`` engajamentos de fato — rola o feed
        e filtra/engaja inline. Para só ao bater a meta, esgotar o feed, ou
        bater o cap de segurança."""
        await self.feed.goto()
        target = self.max_posts
        seen_urns: set[str] = set()
        max_iterations = 60  # cap de segurança (rounds de scroll)
        max_stale = 8  # rounds seguidos sem post novo => feed esgotado
        stale_rounds = 0
        engaged = 0

        await self.feed.scroll_feed(n=2, pause_ms=1500)

        for iteration in range(max_iterations):
            if engaged >= target or self.stop_event.is_set():
                break
            posts = await self.feed.get_posts()
            new_this_round = 0

            for post in posts:
                if engaged >= target or self.stop_event.is_set():
                    break
                sel = await self._select(post, seen_urns)
                if sel == "dup":
                    continue
                new_this_round += 1  # post novo (engajado ou pulado)
                if sel is None:
                    continue
                urn, author, text = sel
                logger.info(f"=== Engajando {engaged + 1}/{target} — {author} ===")
                if await self._engage_post(post, urn, author, text):
                    engaged += 1
                    if engaged < target:
                        await self.feed.random_pause(30, 60)

            if engaged >= target:
                break

            if new_this_round == 0:
                stale_rounds += 1
                logger.info(
                    f"No new posts this round ({stale_rounds}/{max_stale} stale)"
                )
                if stale_rounds >= max_stale:
                    logger.warning("Feed exhausted — no more new posts loading")
                    break
            else:
                stale_rounds = 0
                logger.info(
                    f"Round {iteration + 1}: {new_this_round} new posts, "
                    f"{engaged}/{target} engajados"
                )

            await self.feed.scroll_feed(n=2, pause_ms=1800)

        if engaged < target:
            logger.warning(
                f"Engajou {engaged}/{target} (feed esgotado ou cap atingido)"
            )
        logger.info(
            f"Engagement done. Liked: {self.result.liked} | "
            f"Commented: {self.result.commented} | Shared: {self.result.shared}"
        )
        return self.result
