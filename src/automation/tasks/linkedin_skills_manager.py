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

    async def add_skills(self, skills: list[str], force: bool = False) -> dict:
        """Adiciona cada skill. Recarrega a página entre adições para reset de estado.

        Idempotente por padrão (force=False): lista o perfil uma vez e pula as
        que já existem (case-insensitive), reportando-as em ``skipped``. Para o
        loop ao detectar o limite de competências do LinkedIn, marcando as
        restantes como não adicionadas.

        Retorna ``{added: {skill: bool}, skipped: [skill], limit_reached: bool}``.
        """
        existing: set[str] = set()
        on_page = False  # estamos atualmente na página de skills?
        if not force:
            await self._page_obj.goto()
            current = await self._page_obj.list_skills()
            existing = {s.lower() for s in current}
            on_page = True

        added: dict[str, bool] = {}
        skipped: list[str] = []
        limit_reached = False

        for skill in skills:
            if not force and skill.lower() in existing:
                skipped.append(skill)
                logger.info(f"Skip '{skill}': já existe no perfil")
                continue

            if not on_page:
                await self._page_obj.goto()
            status = await self._page_obj.add_skill(skill)
            on_page = False  # estado sujo após add → recarrega na próxima
            existing.add(skill.lower())

            if status == "added":
                added[skill] = True
            elif status == "duplicate":
                # toast 'já adicionada' — não estava na lista (scroll incompleto),
                # mas existe: trata como pulada, não como falha.
                skipped.append(skill)
            elif status == "limit":
                limit_reached = True
                logger.warning(
                    f"LinkedIn skill limit reached at {len(existing)} skills"
                )
                break
            else:  # failed
                added[skill] = False

        return {"added": added, "skipped": skipped, "limit_reached": limit_reached}

    async def add_missing(self, desired: list[str]) -> dict:
        """Add-only: adiciona apenas as competências ausentes, sem deletar nada.

        Açúcar sobre ``add_skills(force=False)`` (que já filtra existentes).
        """
        return await self.add_skills(desired, force=False)

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
        add_out: dict = {}

        if to_delete:
            delete_results = await self.delete_skills(to_delete)

        if to_add:
            # to_add já exclui existentes; force=True evita re-listar o perfil
            add_out = await self.add_skills(to_add, force=True)

        return {
            "current": current,
            "deleted": delete_results,
            "added": add_out.get("added", {}),
            "skipped": add_out.get("skipped", []),
            "limit_reached": add_out.get("limit_reached", False),
        }
