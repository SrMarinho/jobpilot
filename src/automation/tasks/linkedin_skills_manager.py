"""Task manager: orquestra add/delete/sync de competências no perfil LinkedIn."""

from playwright.async_api import Page
from src.automation.pages.linkedin_skills_page import LinkedInSkillsPage
from src.config.settings import logger


class LinkedInSkillsManager:
    """Orquestra operações de competências via page object."""

    def __init__(self, page: Page, profile_slug: str) -> None:
        self._page_obj = LinkedInSkillsPage(page, profile_slug)

    async def list_skills(self) -> list[str]:
        await self._page_obj.goto()
        return await self._page_obj.list_skills()

    async def add_skills(self, skills: list[str]) -> dict[str, bool]:
        """Adiciona cada skill. Recarrega a página entre adições para reset de estado."""
        results: dict[str, bool] = {}
        for i, skill in enumerate(skills):
            if i > 0:
                await self._page_obj.goto()
            results[skill] = await self._page_obj.add_skill(skill)
            logger.info(f"Add '{skill}': {'ok' if results[skill] else 'failed'}")
        return results

    async def delete_skills(self, skills: list[str]) -> dict[str, bool]:
        """Deleta as skills indicadas. Recarrega a página entre deleções."""
        results: dict[str, bool] = {}
        for i, skill in enumerate(skills):
            if i > 0:
                await self._page_obj.goto()
            results[skill] = await self._page_obj.delete_skill(skill)
            logger.info(f"Delete '{skill}': {'ok' if results[skill] else 'failed'}")
        return results

    async def sync_skills(self, desired: list[str]) -> dict:
        """Sincroniza o perfil com a lista desejada.

        Remove competências não presentes em desired, adiciona as ausentes.
        """
        current = await self.list_skills()
        current_lower = {s.lower(): s for s in current}
        desired_lower = {s.lower(): s for s in desired}

        to_delete = [current_lower[k] for k in current_lower if k not in desired_lower]
        to_add = [desired_lower[k] for k in desired_lower if k not in current_lower]

        logger.info(f"Sync: {len(to_delete)} to delete, {len(to_add)} to add")

        delete_results: dict[str, bool] = {}
        add_results: dict[str, bool] = {}

        if to_delete:
            delete_results = await self.delete_skills(to_delete)

        if to_add:
            add_results = await self.add_skills(to_add)

        return {
            "current": current,
            "deleted": delete_results,
            "added": add_results,
        }
