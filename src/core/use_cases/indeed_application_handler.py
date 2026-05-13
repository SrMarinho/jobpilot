import json
import unicodedata
import asyncio
from playwright.async_api import Page
from src.core.ai.llm_provider import get_llm_provider
from src.config.settings import logger

_QA_FILE = None  # will use same path as job_application_handler

SALARY_KEYWORDS = [
    "salário", "salario", "salary", "remuneração", "remuneracao",
    "pretensão", "pretensao", "compensation", "salarial", "expectativa",
    "remuner", "wage", "pay ", "ctc",
]


def _normalize(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _normalize_question(q: str) -> str:
    return " ".join(_normalize(q).split())


class IndeedApplicationHandler:
    def __init__(self, page: Page, resume: str = ""):
        self.page = page
        self.resume = resume

    async def _get_iframe(self):
        """Find Indeed apply iframe."""
        for sel in ["iframe[src*='apply.indeed.com']", "iframe[class*='indeed-apply']", "iframe#indeed-apply-frame"]:
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
        for sel in ["iframe[src*='apply.indeed.com']", "iframe[class*='indeed-apply']", "iframe#indeed-apply-frame"]:
            try:
                await self.page.wait_for_selector(sel, timeout=timeout * 1000)
                return True
            except Exception:
                pass
        return False

    async def _fill_input(self, el, value: str):
        tag = await el.evaluate("el => el.tagName.toLowerCase()")
        readonly = await el.get_attribute("readonly")
        if tag == "select":
            await el.select_option(value=value)
        elif not readonly:
            await el.fill(value)

    async def _ask_llm(self, question: str, job_title: str, job_description: str) -> str:
        model = get_llm_provider()
        prompt = (
            f"You are applying for the job '{job_title}'. "
            f"Job description: {job_description[:1500]}\n"
            f"Answer the following question concisely for a job application form: {question}\n"
            f"Answer with only the value, no explanation."
        )
        try:
            return await model.complete(prompt)
        except Exception as e:
            logger.error(f"LLM error on '{question[:50]}': {e}")
            return ""

    async def submit(self, salary_expectation: int | str = "", no_submit: bool = False) -> bool:
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
                    for sel in ["input[aria-label*='salari']", "input[aria-label*='salary']", "input[aria-label*='remuner']", "input[placeholder*='salari']", "input[placeholder*='salary']"]:
                        try:
                            inp = iframe.locator(sel)
                            if await inp.is_visible(timeout=500):
                                await inp.fill(str(salary_expectation))
                                logger.info(f"Filled salary input: {salary_expectation}")
                        except Exception:
                            pass

                # Fill required fields in iframe
                for scope in [iframe, self.page]:
                    # inputs
                    inputs = await scope.locator("xpath=.//input[not(@type='hidden') and not(@type='radio') and not(@type='checkbox') and not(@type='submit') and not(@type='button') and @required]").all()
                    for inp in inputs:
                        if not await inp.is_visible():
                            continue
                        readonly = await inp.get_attribute("readonly")
                        if readonly:
                            continue
                        label = await inp.get_attribute("aria-label") or await inp.get_attribute("placeholder") or ""
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
                    radio_groups = await (iframe if step == 0 else self.page).evaluate("""
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
                        radios = (iframe if step == 0 else self.page).locator(f"xpath=.//input[@type='radio' and @name='{name}']")
                        rcount = await radios.count()
                        if rcount > 0:
                            await radios.first.click()
                            logger.info(f"Clicked radio '{label}'")
                except Exception:
                    pass

                # Handle checkboxes
                try:
                    cbs = (iframe if step == 0 else self.page).locator("xpath=.//input[@type='checkbox' and @required]")
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
                        btn = iframe.locator(btn_sel[len("xpath=."):] if btn_sel.startswith("xpath=.") else btn_sel)
                        if await btn.is_visible(timeout=1000) and await btn.is_enabled():
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
        from src.core.use_cases.job_application_handler import _normalize_question
        qa = self._load_qa()
        key = _normalize_question(question)
        entry = qa.get(key)
        if entry is None:
            return None
        if isinstance(entry, dict):
            return entry.get("answer") or None
        return str(entry) if entry else None

    def _save_cached(self, question: str, answer: str, options: list | None = None):
        from src.core.use_cases.job_application_handler import _normalize_question
        qa = self._load_qa()
        key = _normalize_question(question)
        if isinstance(qa.get(key), dict):
            qa[key]["answer"] = answer
        else:
            qa[key] = {"original": question, "answer": answer, "options": options} if options else answer
        self._save_qa(qa)

    def _load_qa(self) -> dict:
        from src.core.use_cases.job_application_handler import _QA_FILE
        if _QA_FILE.exists():
            return json.loads(_QA_FILE.read_text(encoding="utf-8"))
        return {}

    def _save_qa(self, qa: dict):
        from src.core.use_cases.job_application_handler import _QA_FILE
        _QA_FILE.parent.mkdir(parents=True, exist_ok=True)
        _QA_FILE.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
