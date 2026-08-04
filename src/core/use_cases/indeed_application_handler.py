from playwright.async_api import Page
from src.config.settings import logger
from src.core.ai.llm_provider import LLMProvider
from src.core.use_cases.apply.field_filler import FieldFiller
from src.core.use_cases.apply.form_answerer import FormAnswerer


class IndeedApplicationHandler:
    def __init__(
        self,
        page: Page,
        resume: str = "",
        provider: LLMProvider | None = None,
        answerer: FormAnswerer | None = None,
    ):
        self.page = page
        self.resume = resume
        # Mesma peça que o Easy Apply usa — cache de Q&A e prompt são idênticos.
        self.answerer = answerer or FormAnswerer(provider=provider)
        self.fields = FieldFiller(page)

    async def _get_iframe(self):
        """Find Indeed apply iframe."""
        for sel in [
            "iframe[src*='apply.indeed.com']",
            "iframe[class*='indeed-apply']",
            "iframe#indeed-apply-frame",
        ]:
            iframe = self.page.frame_locator(sel)
            try:
                body = iframe.locator("body")
                if await body.is_visible(timeout=3000):
                    logger.info("Found Indeed apply iframe")
                    return iframe
            except Exception:
                continue
        return None

    async def _wait_for_iframe(self, timeout: int = 15) -> bool:
        for sel in [
            "iframe[src*='apply.indeed.com']",
            "iframe[class*='indeed-apply']",
            "iframe#indeed-apply-frame",
        ]:
            try:
                await self.page.wait_for_selector(sel, timeout=timeout * 1000)
                return True
            except Exception:
                pass
        return False

    async def _fill_input(self, el, value: str):
        await self.fields.fill(el, value)

    async def _ask_llm(
        self, question: str, job_title: str, job_description: str
    ) -> str:
        return await self.answerer.ask(question, job_title, job_description)

    async def submit(
        self, salary_expectation: int | str = "", no_submit: bool = False
    ) -> bool:
        if not await self._wait_for_iframe():
            logger.warning("Indeed apply iframe not found")
            return False

        iframe = await self._get_iframe()
        if not iframe:
            return False

        try:
            max_steps = 20
            for step in range(max_steps):
                if no_submit:
                    break

                await self.page.wait_for_timeout(1500)

                # Fill salary if present
                if salary_expectation:
                    for sel in [
                        "input[aria-label*='salari']",
                        "input[aria-label*='salary']",
                        "input[aria-label*='remuner']",
                        "input[placeholder*='salari']",
                        "input[placeholder*='salary']",
                    ]:
                        try:
                            inp = iframe.locator(sel)
                            if await inp.is_visible(timeout=500):
                                await inp.fill(str(salary_expectation))
                                logger.info(
                                    f"Filled salary input: {salary_expectation}"
                                )
                        except Exception:
                            pass

                # Fill required fields in iframe
                for scope in [iframe, self.page]:
                    # inputs
                    inputs = await scope.locator(
                        "xpath=.//input[not(@type='hidden') and not(@type='radio') and not(@type='checkbox') and not(@type='submit') and not(@type='button') and @required]"
                    ).all()
                    for inp in inputs:
                        if not await inp.is_visible():
                            continue
                        readonly = await inp.get_attribute("readonly")
                        if readonly:
                            continue
                        label = (
                            await inp.get_attribute("aria-label")
                            or await inp.get_attribute("placeholder")
                            or ""
                        )
                        if not label:
                            continue
                        cached = self._resolve_cached(label)
                        if cached:
                            await inp.fill(cached)
                        else:
                            answer = await self._ask_llm(label, "", "")
                            if answer:
                                await inp.fill(answer)
                                self._save_cached(label, answer)

                    # selects
                    selects = await scope.locator("xpath=.//select[@required]").all()
                    for sel in selects:
                        if not await sel.is_visible():
                            continue
                        label = await sel.get_attribute("aria-label") or ""
                        if not label:
                            sid = await sel.get_attribute("id")
                            if sid:
                                lbl = scope.locator(f"xpath=.//label[@for='{sid}']")
                                if await lbl.count():
                                    label = (await lbl.first.inner_text()).strip()
                        if not label:
                            continue
                        options = await sel.locator("option").all()
                        option_values = []
                        for opt in options:
                            v = await opt.get_attribute("value")
                            if v and v.strip():
                                option_values.append(v)
                        if not option_values:
                            continue
                        cached = self._resolve_cached(label)
                        if cached:
                            for opt in options:
                                t = (await opt.inner_text()).strip()
                                v = await opt.get_attribute("value")
                                if cached.lower() in t.lower() or cached.lower() == v:
                                    await sel.select_option(value=v)
                                    break
                        else:
                            await sel.select_option(value=option_values[0])
                            self._save_cached(label, option_values[0])

                # Handle radios
                try:
                    radio_groups = await (
                        iframe if step == 0 else self.page
                    ).evaluate("""
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
                    for group in radio_groups:
                        name = group["name"]
                        label = group["label"]
                        if not label:
                            continue
                        radios = (iframe if step == 0 else self.page).locator(
                            f"xpath=.//input[@type='radio' and @name='{name}']"
                        )
                        rcount = await radios.count()
                        if rcount > 0:
                            await radios.first.click()
                            logger.info(f"Clicked radio '{label}'")
                except Exception:
                    pass

                # Handle checkboxes
                try:
                    cbs = (iframe if step == 0 else self.page).locator(
                        "xpath=.//input[@type='checkbox' and @required]"
                    )
                    cb_count = await cbs.count()
                    for c in range(cb_count):
                        cb = cbs.nth(c)
                        if not await cb.is_checked():
                            await cb.click()
                except Exception:
                    pass

                # Submit / Next
                btn_selectors = [
                    "button[type='submit']",
                    "button[aria-label='Submit']",
                    "button[aria-label='Next']",
                    "xpath=.//button[contains(normalize-space(),'Next') or contains(normalize-space(),'Próximo') or contains(normalize-space(),'Proximo') or contains(normalize-space(),'Avançar')]",
                    "xpath=.//button[contains(normalize-space(),'Submit') or contains(normalize-space(),'Enviar') or contains(normalize-space(),'Send')]",
                ]
                clicked = False
                for btn_sel in btn_selectors:
                    try:
                        btn = iframe.locator(
                            btn_sel[len("xpath=.") :]
                            if btn_sel.startswith("xpath=.")
                            else btn_sel
                        )
                        if (
                            await btn.is_visible(timeout=1000)
                            and await btn.is_enabled()
                        ):
                            await btn.click()
                            clicked = True
                            logger.info(f"Indeed form button clicked (step {step + 1})")
                            await self.page.wait_for_timeout(2000)
                            break
                    except Exception:
                        continue

                if not clicked:
                    logger.info(f"No more Indeed form buttons (step {step + 1})")
                    break

            return True
        except Exception as e:
            logger.error(f"Indeed submit error: {e}")
            return False

    def _resolve_cached(self, question: str) -> str | None:
        return self.answerer.resolve(question)

    def _save_cached(self, question: str, answer: str, options: list | None = None):
        self.answerer.store(question, answer, options=options)
