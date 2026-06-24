"""Orchestrator da feature `hired`: descobre contratações recentes e agrega skills.

Fluxo (validado no spike): busca posts de anúncio ordenados por data → filtra
(anúncio + idade ≤ janela + cargo-alvo) → dedup por perfil → abre perfil só p/
skills inline → grava no tracker. Ao fim, o agregado skill→contagem é a saída.

Espelha `ConnectionManager`: 1 goto de descoberta + N gotos de perfil (cap).
"""

import threading

from playwright.async_api import Page

from src.config.settings import logger
from src.automation.pages import HiredPostPage
from src.automation.url_builder import build_linkedin_hired_posts_urls
from src.core.ai.llm_provider import LLMProvider
from src.core.use_cases.hired_posts import (
    is_hire_announcement,
    matches_role,
    post_age_days,
)
from src.core.use_cases.hired_skill_extractor import extract_tech_skills
from src.core.use_cases.hired_skills_tracker import HiredSkillsTracker


class HiredProfileManager:
    def __init__(
        self,
        page: Page,
        role: str,
        llm_provider: LLMProvider | None = None,
        days: int = 90,
        max_profiles: int = 10,
        dry_run: bool = False,
        no_dedup: bool = False,
        stop_event: threading.Event | None = None,
    ):
        self.page = page
        self.role = role
        self.llm = llm_provider
        self.days = days
        self.max_profiles = max_profiles
        self.dry_run = dry_run
        self.no_dedup = no_dedup
        self.stop_event = stop_event or threading.Event()
        self.page_obj = HiredPostPage(page)
        self.tracker = HiredSkillsTracker()
        self.collected = 0
        self.skipped_dup = 0

    @staticmethod
    def _company_from_headline(headline: str) -> str:
        # headline LinkedIn costuma ser "Cargo at Empresa" / "Cargo na Empresa".
        for sep in (" at ", " na ", " @ ", " | "):
            if sep in headline:
                return headline.split(sep, 1)[1].strip()[:80]
        return ""

    async def _collect_posts(self) -> list[dict]:
        """Busca posts em URLs separadas por termo de anúncio, dedup por profile_url."""
        urls = build_linkedin_hired_posts_urls(self.role)
        seen_urls: set[str] = set()
        all_posts: list[dict] = []
        for url in urls:
            if self.stop_event.is_set() or self.collected >= self.max_profiles:
                break
            logger.info(f"[hired] busca: {url}")
            posts = await self.page_obj.scrape_posts(url, limit=self.max_profiles * 3)
            logger.info(f"[hired] Posts encontrados: {len(posts)}")
            for post in posts:
                purl = post.get("profile_url", "")
                if purl and purl not in seen_urls:
                    seen_urls.add(purl)
                    all_posts.append(post)
        return all_posts

    async def run(self) -> HiredSkillsTracker:
        posts = await self._collect_posts()

        for post in posts:
            if self.stop_event.is_set() or self.collected >= self.max_profiles:
                break
            post_text = post.get("text", "")
            if not is_hire_announcement(post_text):
                continue
            age_days = post_age_days(post_text)
            if age_days is None or age_days > self.days:
                continue
            if not matches_role(post_text, "", self.role):
                continue
            profile_url = post["profile_url"]
            author = post.get("author", "")
            if not self.no_dedup and self.tracker.already_seen(profile_url):
                self.skipped_dup += 1
                logger.info(f"[hired] dup, pulando: {author}")
                continue

            if self.dry_run:
                logger.info(f"[dry-run] {author} | {age_days}d | {post_text[:80]!r}")
                self.collected += 1
                continue

            profile_data = await self.page_obj.scrape_profile_skills(profile_url)
            headline = profile_data.get("headline", "")
            inline_skills = profile_data.get("top_skills", [])
            # LLM extrai skills técnicas (cobre perfis sem bloco inline + filtra
            # ruído). Fallback p/ inline quando sem LLM ou falha.
            if self.llm is not None:
                top_skills = await extract_tech_skills(
                    self.llm, profile_data.get("profile_text", ""), inline_skills
                )
            else:
                top_skills = inline_skills
            self.tracker.add_profile(
                profile_url=profile_url,
                name=author,
                headline=headline,
                company=self._company_from_headline(headline),
                top_skills=top_skills,
                age_days=age_days,
                role=self.role,
            )
            self.collected += 1
            logger.info(
                f"[hired] {self.collected}/{self.max_profiles} {author} "
                f"skills={top_skills}"
            )
            await self.page.wait_for_timeout(1500)

        logger.info(
            f"[hired] coletados={self.collected} dups_puladas={self.skipped_dup}"
        )
        return self.tracker
