"""Orquestrador do Easy Apply: percorre as etapas do formulário até enviar.

Compõe ``FormAnswerer`` (o que responder), ``FieldFiller`` (como escrever) e
``ModalDriver`` (o modal) — não herda de nenhum deles, então cada peça continua
testável e substituível isoladamente.
"""

from playwright.async_api import Page

from src.config.settings import logger
from src.core.ai.llm_provider import LLMProvider
from src.core.use_cases.apply.field_filler import FieldFiller, PLACEHOLDER_VALUES
from src.core.use_cases.apply.form_answerer import FormAnswerer
from src.core.use_cases.apply.modal_driver import ModalDriver
from src.core.use_cases.form_answer_cache import SALARY_KEYWORDS

# Botões de avanço/envio, em ordem de preferência.
SUBMIT_BUTTONS = [
    "button[aria-label='Submit application']",
    "button[aria-label='Enviar candidatura']",
    "button[type='submit']",
    "xpath=//button[contains(@aria-label,'Next') or contains(normalize-space(),'Next') or contains(normalize-space(),'Próximo') or contains(normalize-space(),'Proximo') or contains(normalize-space(),'Avançar')]",
    "xpath=//button[contains(@aria-label,'Review') or contains(normalize-space(),'Review') or contains(normalize-space(),'Revisar')]",
    "xpath=//button[contains(@aria-label,'Done') or contains(normalize-space(),'Done') or contains(normalize-space(),'Concluído')]",
    "button[class*=artdeco-button--primary]",
]
# Só os que de fato enviam — usados na checagem final, fora do loop de etapas.
FINAL_SUBMIT_BUTTONS = SUBMIT_BUTTONS[:3]
# Texto que identifica o botão como "envia agora" e não "avança de etapa".
SUBMIT_WORDS = ("submit", "enviar", "send")

MAX_STEPS = 30
# Mesma etapa repetida e sinal de campo rejeitado: o modal nao avanca e o loop
# gasta os 30 passos pra terminar sem enviar nada.
STUCK_LIMIT = 3
STEP_SETTLE_MS = 1500
AFTER_SUBMIT_MS = 2000


def _strip_xpath(selector: str) -> str:
    return selector[len("xpath=") :] if selector.startswith("xpath=") else selector


class EasyApplyHandler:
    """Preenche e envia o formulário Easy Apply do LinkedIn/Glassdoor."""

    def __init__(
        self,
        page: Page,
        resume: str = "",
        provider: LLMProvider | None = None,
        answerer: FormAnswerer | None = None,
    ):
        self.page = page
        self.resume = resume
        self.answerer = answerer or FormAnswerer(provider=provider)
        self.fields = FieldFiller(page)
        self.modal = ModalDriver(page)

    # ── Um campo ─────────────────────────────────────────────────────────────

    async def _fill_field(
        self,
        element,
        question: str,
        job_title: str,
        job_description: str,
        salary: int | str,
    ) -> None:
        """Responde e preenche um campo. Salário tem atalho: valor já é conhecido."""
        if salary and any(k in question.lower() for k in SALARY_KEYWORDS):
            await self.fields.fill(element, str(salary))
            logger.info(f"Filled salary with '{salary}'")
            return

        cached = self.answerer.resolve(question)
        if cached:
            await self.fields.fill(element, cached)
            logger.info(f"Filled '{question[:40]}' with cached: '{cached}'")
            return

        if await self.fields.tag_of(element) == "select":
            await self._fill_select(element, question, job_title, job_description)
            return

        answer = await self.answerer.ask(question, job_title, job_description)
        if answer:
            await element.fill(answer)
            self.answerer.store(question, answer)
            logger.info(f"LLM filled '{question[:40]}' with '{answer[:40]}'")

    async def _fill_select(
        self, element, question: str, job_title: str, job_description: str
    ) -> None:
        """Escolhe uma <option>: LLM se ela existir na lista, senão a primeira."""
        values = await self.fields.option_values(element)
        if not values:
            logger.warning(f"Select has no options, skipping: '{question[:40]}'")
            return
        answer = await self.answerer.ask(
            f"{question} (options: {values})", job_title, job_description
        )
        if answer in values:
            await element.select_option(value=answer)
            self.answerer.store(question, answer, options=values)
            logger.info(f"LLM selected '{answer}' for '{question[:40]}'")
            return
        await element.select_option(value=values[0])
        logger.info(f"Selected default '{values[0]}' for '{question[:40]}'")

    # ── Um escopo (inputs, textareas, selects) ───────────────────────────────

    async def _fill_scope(
        self,
        scope,
        job_title: str,
        job_description: str,
        salary: int | str,
        visited_select_ids: set,
    ) -> None:
        await self._fill_text_inputs(scope, job_title, job_description, salary)
        await self._fill_textareas(scope, job_title, job_description)
        await self._fill_selects(
            scope, job_title, job_description, salary, visited_select_ids
        )

    async def _fill_text_inputs(
        self, scope, job_title: str, job_description: str, salary: int | str
    ) -> None:
        inputs = await scope.locator(
            "xpath=.//input[not(@type='hidden') and not(@type='radio') "
            "and not(@type='checkbox') and not(@type='submit') "
            "and not(@type='button') and not(@type='file')]"
        ).all()
        logger.info(f"Input elements found in scope: {len(inputs)}")
        for element in inputs:
            try:
                if not await element.is_visible():
                    continue
                if await element.get_attribute("readonly"):
                    continue
                label = await self.fields.label_of(element, scope)
                if not label:
                    continue
                await self._fill_field(
                    element, label, job_title, job_description, salary
                )
            except Exception as e:
                logger.warning(f"Input error: {e}")

    async def _fill_textareas(
        self, scope, job_title: str, job_description: str
    ) -> None:
        textareas = await scope.locator("xpath=.//textarea").all()
        logger.info(f"Textarea elements found in scope: {len(textareas)}")
        for element in textareas:
            try:
                if not await element.is_visible():
                    continue
                if await element.get_attribute("readonly"):
                    continue
                label = await self.fields.label_of(element, scope)
                if not label:
                    continue
                answer, from_cache = await self.answerer.answer(
                    label, job_title, job_description
                )
                if not answer:
                    continue
                await element.fill(answer)
                if not from_cache:
                    self.answerer.store(label, answer)
                logger.info(f"Filled textarea '{label[:30]}'")
            except Exception as e:
                logger.warning(f"Textarea error: {e}")

    async def _fill_selects(
        self,
        scope,
        job_title: str,
        job_description: str,
        salary: int | str,
        visited_select_ids: set,
    ) -> None:
        selects = await scope.locator("xpath=.//select").all()
        logger.info(f"Select elements found in scope: {len(selects)}")
        for element in selects:
            select_id = await element.get_attribute("id") or ""
            # Um select já visitado numa etapa anterior não deve ser reescrito.
            if select_id in visited_select_ids:
                continue
            visited_select_ids.add(select_id)
            try:
                if not await element.is_visible():
                    logger.warning(f"Select not displayed (hidden?): id={select_id!r}")
                    continue
                current = await element.evaluate("el => el.value")
                if current not in PLACEHOLDER_VALUES:
                    logger.info(f"Select already filled (val={current!r}), skipping")
                    continue
                label = await self.fields.label_of(element, scope)
                if not label:
                    logger.warning(f"Select label unknown, skipping: id={select_id!r}")
                    continue
                await self._fill_field(
                    element, label, job_title, job_description, salary
                )
            except Exception as e:
                logger.warning(f"Select error: {e}")

    # ── Radios ───────────────────────────────────────────────────────────────

    async def _fill_radio_groups(self, job_title: str, job_description: str) -> None:
        """Responde um radio por grupo (agrupados por atributo ``name``)."""
        try:
            groups = await self.page.evaluate("""
                () => {
                    const inputs = document.querySelectorAll('input[type="radio"]');
                    const seen = new Set();
                    const groups = [];
                    inputs.forEach(inp => {
                        const name = inp.name;
                        if (!name || seen.has(name)) return;
                        seen.add(name);
                        const id = inp.id;
                        let label = '';
                        if (id) {
                            const l = document.querySelector('label[for="'+id+'"]');
                            if (l) label = l.innerText.trim();
                        }
                        if (!label) label = inp.getAttribute('aria-label') || '';
                        groups.push({name, label});
                    });
                    return groups;
                }
            """)
        except Exception as e:
            logger.warning(f"Radio group scan error: {e}")
            return

        for group in groups:
            if not group["label"]:
                continue
            try:
                await self._fill_radio_group(
                    group["name"], group["label"], job_title, job_description
                )
            except Exception as e:
                logger.warning(f"Radio fill error on '{group['label'][:40]}': {e}")

    async def _fill_radio_group(
        self, name: str, label: str, job_title: str, job_description: str
    ) -> None:
        logger.info(f"Radio group: '{label}'")
        options = self.page.locator(f"xpath=//input[@type='radio' and @name='{name}']")
        count = await options.count()
        if count == 0:
            return
        if count == 1:
            await options.first.click()
            logger.info(f"Clicked single radio for '{label}'")
            return

        labels = [await self.fields.radio_label(options.nth(i)) for i in range(count)]

        cached = self.answerer.resolve(label)
        if cached:
            for i in range(count):
                value = (await options.nth(i).get_attribute("value") or "").lower()
                if cached.lower() in (value, labels[i].lower()):
                    await options.nth(i).click()
                    logger.info(f"Selected cached radio '{cached}' for '{label}'")
                    return
            await options.first.click()
            logger.info(f"Selected first radio for '{label}' (cache mismatch)")
            return

        answer = await self.answerer.ask(
            f"{label} (options: {labels})", job_title, job_description
        )
        if answer:
            for i, option_label in enumerate(labels):
                if (
                    answer.lower() in option_label.lower()
                    or option_label.lower() in answer.lower()
                ):
                    await options.nth(i).click()
                    self.answerer.store(label, option_label)
                    logger.info(f"LLM selected radio '{option_label}' for '{label}'")
                    return
            await options.first.click()
            logger.info(f"Selected first radio for '{label}' (LLM no match)")
            return

        await options.first.click()
        logger.info(f"Selected default radio for '{label}'")

    # ── Obrigatórios que sobraram ────────────────────────────────────────────

    async def _fill_remaining_required(
        self, job_title: str, job_description: str, salary: int | str
    ) -> None:
        """Varre a página inteira atrás de required ainda vazio.

        Roda depois do escopo do modal porque o LinkedIn às vezes renderiza
        campos obrigatórios fora do container que o modal expõe.
        """
        for element in await self.fields.required_unfilled():
            try:
                label = await self.fields.label_of(element, use_parent_text=True)
                if not label:
                    continue
                await self._fill_field(
                    element, label, job_title, job_description, salary
                )
            except Exception as e:
                logger.warning(f"Required-field fill error: {e}")

    # ── Envio ────────────────────────────────────────────────────────────────

    @staticmethod
    def _is_submit(button_text: str) -> bool:
        return any(word in button_text for word in SUBMIT_WORDS)

    async def _advance(self, step: int) -> bool | None:
        """Clica o botão da etapa.

        ``True`` = candidatura enviada, ``False`` = avançou de etapa,
        ``None`` = não há mais botão (fim do formulário).
        """
        for selector in SUBMIT_BUTTONS:
            try:
                button = self.page.locator(_strip_xpath(selector))
                if not (
                    await button.is_visible(timeout=1000) and await button.is_enabled()
                ):
                    continue
                text = (await button.inner_text()).strip().lower()
                if self._is_submit(text):
                    logger.info(f"Submit button clicked: '{text}'")
                    await button.click()
                    await self.page.wait_for_timeout(AFTER_SUBMIT_MS)
                    return True
                await button.click()
                logger.info(f"Clicked '{text}' (step {step + 1})")
                await self.modal.wait_closed(timeout_s=3)
                return False
            except Exception:
                continue
        return None

    async def _final_submit(self) -> bool:
        """Última tentativa de envio depois que o loop de etapas acabou."""
        for selector in FINAL_SUBMIT_BUTTONS:
            try:
                button = self.page.locator(_strip_xpath(selector))
                if not (
                    await button.is_visible(timeout=1000) and await button.is_enabled()
                ):
                    continue
                text = (await button.inner_text()).strip().lower()
                if self._is_submit(text):
                    await button.click()
                    logger.info("Final submit clicked")
                    await self.page.wait_for_timeout(AFTER_SUBMIT_MS)
                    return True
            except Exception:
                continue
        return False

    async def submit_easy_apply(
        self,
        salary_expectation: int | str = "",
        job_title: str = "",
        job_description: str = "",
        no_submit: bool = False,
    ) -> bool:
        """Preenche o formulário etapa a etapa e envia.

        Com ``no_submit=True`` nada é preenchido nem enviado — é o modo de
        inspeção, que só confirma que o modal abriu.
        """
        salary_filled = False
        visited_select_ids: set[str] = set()

        try:
            await self.modal.wait_open()
            if no_submit:
                logger.info("no_submit: modal aberto, nada preenchido")
                return True

            last_signature: str | None = None
            repeats = 0

            for step in range(MAX_STEPS):
                await self.page.wait_for_timeout(STEP_SETTLE_MS)

                signature = await self._step_signature()
                if signature and signature == last_signature:
                    repeats += 1
                    if repeats >= STUCK_LIMIT:
                        logger.error(
                            f"Formulário travado na mesma etapa {repeats}x "
                            f"(step {step + 1}) — algum campo não foi aceito"
                        )
                        return False
                else:
                    repeats = 0
                    last_signature = signature

                if not salary_filled and salary_expectation:
                    salary_filled = await self.fields.fill_salary(salary_expectation)

                scope = await self.modal.current()
                await self._fill_scope(
                    scope,
                    job_title,
                    job_description,
                    salary_expectation,
                    visited_select_ids,
                )
                await self._fill_radio_groups(job_title, job_description)
                await self.fields.check_required_checkboxes()
                await self._fill_remaining_required(
                    job_title, job_description, salary_expectation
                )

                advanced = await self._advance(step)
                if advanced is True:
                    return True
                if advanced is None:
                    logger.info(f"No more buttons to click (step {step + 1})")
                    break

            # O retorno tem que refletir o envio: dar True aqui contava como
            # candidatura enviada um formulário que parou no meio.
            sent = await self._final_submit()
            if not sent:
                logger.error(
                    "Easy Apply terminou sem enviar — nenhum botão de envio ativo"
                )
            return sent
        except Exception:
            logger.exception("Easy Apply error")
            return False

    async def _step_signature(self) -> str:
        """Identidade da etapa atual, pra detectar que o modal não avançou."""
        try:
            scope = await self.modal.current()
            text = await scope.inner_text()
        except Exception:
            return ""
        return " ".join(text.split())[:400]


# Nome antigo — os managers de LinkedIn/Glassdoor ainda importam por ele.
JobApplicationHandler = EasyApplyHandler
