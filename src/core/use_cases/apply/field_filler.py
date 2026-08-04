"""Primitivas de DOM do formulário: escrever num campo e descobrir seu rótulo.

Não sabe *o que* responder — só como escrever. Quem decide o conteúdo é o
``FormAnswerer``. A descoberta de rótulo (``label[for]`` → ``aria-label`` →
``placeholder`` → ``legend`` do fieldset → texto do pai) estava reimplementada
em quatro métodos da classe monolítica, cada um cobrindo um subconjunto
diferente da cadeia; aqui é uma só.
"""

from playwright.async_api import Page

from src.automation.pages.selectors import T_FAST, first_visible
from src.config.settings import logger

# Setter que dispara o evento 'change' — selects controlados por React ignoram
# uma atribuição direta de .value e não atualizam o estado do componente.
_REACT_SELECT_SETTER = """
var setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
var event = new Event('change', { bubbles: true });
setter.call(arguments[0], arguments[1]);
arguments[0].dispatchEvent(event);
"""

# Rótulo pelo <legend> do <fieldset> que envolve o campo.
_LEGEND_JS = """el => {
    const p = el.closest('fieldset');
    if (p) {
        const leg = p.querySelector('legend');
        if (leg) return leg.innerText.trim();
    }
    return '';
}"""

# Rótulo de um radio: label[for] → aria-label → value.
_RADIO_LABEL_JS = """el => {
    const id = el.id;
    if (id) {
        const l = document.querySelector('label[for="'+id+'"]');
        if (l) return l.innerText.trim();
    }
    return el.getAttribute('aria-label') || el.value;
}"""

_SALARY_INPUT = [
    "input[type='text'][aria-label*='salari']",
    "input[aria-label*='salari']",
    "input[type='text'][aria-label*='salary']",
    "input[aria-label*='salary']",
    "input[aria-label*='remuner']",
    "input[placeholder*='salari']",
    "input[placeholder*='salary']",
    "input[placeholder*='remuner']",
]

# Valores que um select mostra quando ainda não foi respondido.
PLACEHOLDER_VALUES = ("", "Select...", "Selecione...")

REQUIRED_FIELDS_XPATH = (
    "xpath=//input[@required and @type!='hidden'] "
    "| //select[@required] | //textarea[@required]"
)


class FieldFiller:
    def __init__(self, page: Page):
        self.page = page

    # ── Escrita ──────────────────────────────────────────────────────────────

    @staticmethod
    async def tag_of(element) -> str:
        return await element.evaluate("el => el.tagName.toLowerCase()")

    async def fill(self, element, value: str) -> None:
        """Escreve ``value`` respeitando o tipo do campo. Ignora readonly."""
        tag = await self.tag_of(element)
        if tag == "select":
            await element.select_option(value=value)
        elif await element.get_attribute("readonly"):
            return
        else:
            await element.fill(value)

    async def fill_react_select(self, element, value: str) -> None:
        """Escreve num select controlado por React (dispara 'change')."""
        tag = await self.tag_of(element)
        if tag == "select":
            await self.page.evaluate(_REACT_SELECT_SETTER, element, value)
        elif tag == "input":
            await element.fill(value)

    async def is_unfilled(self, element) -> bool:
        tag = await self.tag_of(element)
        if tag == "select":
            value = await element.evaluate("el => el.value")
            return not value
        return not (await element.input_value()).strip()

    async def fill_salary(self, salary: int | str) -> bool:
        """Preenche campos que só pedem o número, sem enunciado de pergunta."""
        field = await first_visible(
            self.page,
            _SALARY_INPUT,
            field="salary input",
            timeout=T_FAST,
            required=False,
        )
        if field is None:
            return False
        try:
            await field.fill(str(salary))
            logger.info(f"Filled salary input: {salary}")
            return True
        except Exception:
            return False

    async def check_required_checkboxes(self) -> None:
        try:
            boxes = self.page.locator("xpath=//input[@type='checkbox' and @required]")
            for i in range(await boxes.count()):
                box = boxes.nth(i)
                if not await box.is_checked():
                    await box.click()
                    logger.info("Checked required checkbox")
        except Exception:
            pass

    # ── Descoberta de rótulo ─────────────────────────────────────────────────

    async def label_of(
        self, element, scope=None, *, use_parent_text: bool = False
    ) -> str:
        """Rótulo do campo, tentando as fontes em ordem de confiabilidade.

        ``label[for]`` → ``aria-label`` → ``placeholder`` → ``legend`` do
        fieldset → (opcional) texto do elemento pai. ``scope`` restringe a busca
        do ``label[for]`` ao modal; sem ele, procura na página inteira.
        """
        root = scope if scope is not None else self.page
        prefix = ".//" if scope is not None else "//"

        element_id = await element.get_attribute("id")
        if element_id:
            label = root.locator(f"xpath={prefix}label[@for='{element_id}']")
            if await label.count():
                text = (await label.first.inner_text()).strip()
                if text:
                    return text

        for attribute in ("aria-label", "placeholder"):
            value = (await element.get_attribute(attribute) or "").strip()
            if value:
                return value

        if use_parent_text:
            try:
                parent_text = (await element.locator("xpath=..").inner_text()).strip()
                if parent_text:
                    return parent_text
            except Exception:
                pass

        try:
            legend = await element.evaluate(_LEGEND_JS)
            if legend:
                return legend
        except Exception:
            pass

        return ""

    @staticmethod
    async def radio_label(element) -> str:
        try:
            return await element.evaluate(_RADIO_LABEL_JS)
        except Exception:
            return ""

    # ── Opções de select ─────────────────────────────────────────────────────

    @staticmethod
    async def option_values(select) -> list[str]:
        """Valores não-vazios das <option> de um select."""
        values = []
        for option in await select.locator("option").all():
            value = await option.get_attribute("value")
            if value and value.strip():
                values.append(value)
        return values

    @staticmethod
    async def option_pairs(select) -> list[tuple[str, str]]:
        """Pares ``(value, texto)`` das <option> de um select."""
        pairs = []
        for option in await select.locator("option").all():
            value = await option.get_attribute("value")
            text = (await option.inner_text()).strip()
            pairs.append((value or "", text))
        return pairs

    async def required_unfilled(self, scope=None) -> list:
        """Campos obrigatórios visíveis que ainda estão vazios."""
        root = scope if scope is not None else self.page
        pending = []
        for element in await root.locator(REQUIRED_FIELDS_XPATH).all():
            try:
                if not await element.is_visible():
                    continue
                if await self.is_unfilled(element):
                    pending.append(element)
            except Exception:
                continue
        return pending
