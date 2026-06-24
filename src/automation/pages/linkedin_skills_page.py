"""Page object: gerencia competências do perfil LinkedIn.

Seletores best-effort para DOM obfuscado do LinkedIn (2025-2026).
Múltiplos fallbacks por operação para máxima resiliência.
"""

from playwright.async_api import Page, Locator
from src.config.settings import logger

SKILLS_DETAILS_URL = "https://www.linkedin.com/in/{slug}/details/skills/"

_LIST_SKILLS_JS = """
() => {
    const skills = new Set();
    const items = document.querySelectorAll(
        "li.pvs-list__item--line-separated, li.pvs-list__item--no-padding-when-first, li.artdeco-list__item"
    );
    for (const item of items) {
        const spans = item.querySelectorAll("span[aria-hidden='true']");
        for (const span of spans) {
            const t = (span.innerText || span.textContent || '').trim();
            if (t && t.length >= 2 && t.length <= 80 && !t.includes('\\n') && !t.includes('·')) {
                skills.add(t);
                break;
            }
        }
    }
    return [...skills];
}
"""


class LinkedInSkillsPage:
    """Interage com a seção de competências do perfil LinkedIn via Playwright."""

    def __init__(self, page: Page, profile_slug: str) -> None:
        self.page = page
        self.url = SKILLS_DETAILS_URL.format(slug=profile_slug)

    async def goto(self) -> None:
        logger.info(f"Opening skills page: {self.url}")
        await self.page.goto(self.url, wait_until="domcontentloaded")
        await self._wait_for_content()

    async def _wait_for_content(self, timeout_ms: int = 30_000) -> None:
        try:
            await self.page.wait_for_function(
                """() => {
                    const t = (document.body.innerText || '').toLowerCase();
                    return t.includes('competência') || t.includes('skill');
                }""",
                timeout=timeout_ms,
            )
        except Exception:
            logger.warning("Skills page content wait timed out; proceeding anyway")
        await self.page.wait_for_timeout(1500)

    async def list_skills(self) -> list[str]:
        """Retorna nomes de todas as competências visíveis na página."""
        try:
            result = await self.page.evaluate(_LIST_SKILLS_JS)
            skills = [s for s in (result or []) if s]
            logger.info(f"Found {len(skills)} skills on page")
            return skills
        except Exception as e:
            logger.warning(f"Failed to list skills: {e}")
            return []

    async def delete_skill(self, skill_name: str) -> bool:
        """Deleta uma competência pelo nome. Retorna True se deletada."""
        logger.info(f"Deleting skill: {skill_name!r}")

        edit_btn = await self._find_skill_edit_button(skill_name)
        if edit_btn is None:
            logger.warning(f"Edit button not found for skill: {skill_name!r}")
            return False

        await edit_btn.click()
        await self.page.wait_for_timeout(1500)

        delete_btn = await self._find_button(
            selectors=[
                "button[aria-label='Excluir competência']",
                "button[aria-label='Delete skill']",
                "button[aria-label*='Excluir']",
                "button[aria-label*='Delete']",
            ],
            fallback_texts=["Excluir", "Delete"],
        )
        if delete_btn is None:
            logger.warning(f"Delete button not found in modal for: {skill_name!r}")
            await self._close_modal()
            return False

        await delete_btn.click()
        await self.page.wait_for_timeout(1000)
        await self._try_confirm_delete()
        await self.page.wait_for_timeout(1500)

        logger.info(f"Skill deleted: {skill_name!r}")
        return True

    async def add_skill(self, skill_name: str) -> bool:
        """Adiciona uma competência pelo nome. Retorna True se adicionada."""
        logger.info(f"Adding skill: {skill_name!r}")

        add_btn = await self._find_button(
            selectors=[
                "a[href*='add'][href*='skill']",
                "button[aria-label='Adicionar competência']",
                "button[aria-label='Add skill']",
                "a[aria-label*='Adicionar competência']",
                "a[aria-label*='Add skill']",
            ],
            fallback_texts=["Adicionar competência", "Add skill"],
        )
        if add_btn is None:
            logger.warning("Add skill button not found")
            return False

        await add_btn.click()
        await self.page.wait_for_timeout(2000)

        skill_input = await self._find_skill_input()
        if skill_input is None:
            logger.warning("Skill typeahead input not found in modal")
            await self._close_modal()
            return False

        await skill_input.click()
        await skill_input.fill(skill_name)
        await self.page.wait_for_timeout(1500)

        selected = await self._select_suggestion(skill_name)
        if not selected:
            logger.warning(f"No autocomplete suggestion matched: {skill_name!r}")
            await self._close_modal()
            return False

        await self.page.wait_for_timeout(800)

        save_btn = await self._find_button(
            selectors=[
                "button[aria-label='Salvar']",
                "button[aria-label='Save']",
            ],
            fallback_texts=["Salvar", "Save"],
        )
        if save_btn is None:
            logger.warning("Save button not found after selecting skill")
            await self._close_modal()
            return False

        await save_btn.click()
        await self.page.wait_for_timeout(2000)

        logger.info(f"Skill added: {skill_name!r}")
        return True

    async def _find_skill_edit_button(self, skill_name: str) -> Locator | None:
        """Encontra o botão de edição de uma competência específica."""
        skill_lower = skill_name.lower()

        for aria_label in [
            f"Editar {skill_name}",
            f"Edit {skill_name}",
            f"Editar competência: {skill_name}",
            f"Edit skill: {skill_name}",
        ]:
            try:
                btn = self.page.locator(f"button[aria-label='{aria_label}']")
                if await btn.is_visible(timeout=800):
                    return btn
            except Exception:
                pass

        # Fallback: busca o item que contém o nome da competência
        try:
            items = self.page.locator(
                "li.pvs-list__item--line-separated,"
                "li.pvs-list__item--no-padding-when-first,"
                "li.artdeco-list__item"
            )
            count = await items.count()
            for i in range(count):
                item = items.nth(i)
                try:
                    text = (await item.inner_text()).lower()
                except Exception:
                    continue
                if skill_lower not in text:
                    continue
                for selector in [
                    "button[aria-label*='Editar']",
                    "button[aria-label*='Edit']",
                    "button.optional-action-icon-button",
                    "button[aria-label*='pencil']",
                ]:
                    try:
                        btn = item.locator(selector)
                        if await btn.count() > 0 and await btn.first.is_visible(timeout=500):
                            return btn.first
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Error in skill item search: {e}")

        return None

    async def _find_button(
        self,
        selectors: list[str],
        fallback_texts: list[str] | None = None,
        timeout: int = 3000,
    ) -> Locator | None:
        """Tenta múltiplos seletores para encontrar um botão."""
        for selector in selectors:
            try:
                btn = self.page.locator(selector)
                if await btn.count() > 0 and await btn.first.is_visible(timeout=timeout):
                    return btn.first
            except Exception:
                pass

        for text in (fallback_texts or []):
            try:
                btn = self.page.get_by_role("button", name=text, exact=False)
                if await btn.count() > 0 and await btn.first.is_visible(timeout=timeout):
                    return btn.first
            except Exception:
                pass

        return None

    async def _find_skill_input(self) -> Locator | None:
        """Encontra o input de typeahead no modal de adicionar competência."""
        for selector in [
            "input[name='skill-name-typeahead-input']",
            "input[id*='skill']",
            "input[aria-label*='Competência']",
            "input[aria-label*='Skill']",
            "input[placeholder*='competência']",
            "input[placeholder*='skill']",
            ".artdeco-typeahead__input",
            "input[role='combobox']",
        ]:
            try:
                inp = self.page.locator(selector)
                if await inp.count() > 0 and await inp.first.is_visible(timeout=2000):
                    return inp.first
            except Exception:
                pass
        return None

    async def _select_suggestion(self, skill_name: str) -> bool:
        """Seleciona a melhor sugestão do autocomplete."""
        skill_lower = skill_name.lower()

        for selector in [
            "[role='listbox'] [role='option']",
            "[role='option']",
            ".artdeco-typeahead__results li",
            ".search-typeahead-v2__hit",
            "ul[role='listbox'] li",
        ]:
            try:
                options = self.page.locator(selector)
                count = await options.count()
                if count == 0:
                    continue

                for i in range(min(count, 8)):
                    opt = options.nth(i)
                    try:
                        text = (await opt.inner_text()).strip().lower()
                    except Exception:
                        continue
                    if skill_lower in text or text.startswith(skill_lower[:4]):
                        await opt.click()
                        return True

                # Fallback: primeira opção disponível
                if await options.first.is_visible(timeout=500):
                    await options.first.click()
                    return True

            except Exception:
                pass

        return False

    async def _try_confirm_delete(self) -> None:
        """Confirma diálogo de exclusão, se aparecer."""
        for selector in [
            "button[aria-label='Excluir']",
            "button[aria-label='Delete']",
        ]:
            try:
                btn = self.page.locator(selector)
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    return
            except Exception:
                pass

        for text in ["Excluir", "Delete", "Confirmar", "Confirm"]:
            try:
                btn = self.page.get_by_role("button", name=text, exact=True)
                if await btn.is_visible(timeout=1000):
                    await btn.click()
                    return
            except Exception:
                pass

    async def _close_modal(self) -> None:
        """Fecha o modal atual via botão Fechar ou Escape."""
        try:
            dismiss = self.page.locator(
                "button[aria-label='Fechar'],"
                "button[aria-label='Close'],"
                "button[aria-label='Dismiss']"
            )
            if await dismiss.first.is_visible(timeout=1000):
                await dismiss.first.click()
                return
        except Exception:
            pass
        try:
            await self.page.keyboard.press("Escape")
        except Exception:
            pass
