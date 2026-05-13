import json
import unicodedata
import asyncio
import os
from pathlib import Path
from playwright.async_api import Page
from src.core.ai.llm_provider import get_llm_provider
from src.config.settings import logger

SALARY_KEYWORDS = [
    "salário", "salario", "salary", "remuneração", "remuneracao",
    "pretensão", "pretensao", "compensation", "salarial", "expectativa",
    "remuner", "wage", "pay ", "ctc",
]

_QA_FILE = Path(__file__).parent.parent.parent.parent / ".local" / "files" / "qa.json"


def _normalize(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _normalize_question(q: str) -> str:
    return " ".join(_normalize(q).split())


# React-aware select setter
_REACT_SELECT_SETTER = """
var setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
var event = new Event('change', { bubbles: true });
setter.call(arguments[0], arguments[1]);
arguments[0].dispatchEvent(event);
"""


class JobApplicationHandler:
    def __init__(self, page: Page, resume: str = ""):
        self.page = page
        self.resume = resume

    # ── select helpers ───────────────────────────────────────────────────────

    async def _fill_input(self, el, value: str):
        tag = await el.evaluate("el => el.tagName.toLowerCase()")
        readonly = await el.get_attribute("readonly")
        if tag == "select":
            await el.select_option(value=value)
        elif readonly:
            pass
        else:
            await el.fill(value)

    async def _fill_react_select(self, el, value: str):
        tag = await el.evaluate("el => el.tagName.toLowerCase()")
        if tag == "select":
            await self.page.evaluate(_REACT_SELECT_SETTER, el, value)
        elif tag == "input":
            await el.fill(value)

    async def _is_unfilled(self, el) -> bool:
        tag = await el.evaluate("el => el.tagName.toLowerCase()")
        if tag == "select":
            val = await el.evaluate("el => el.value")
            return not val or val == ""
        else:
            val = await el.input_value()
            return not val.strip()

    # ── LLM-driven answer ────────────────────────────────────────────────────

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

    # ── QA cache ─────────────────────────────────────────────────────────────

    def _load_qa(self) -> dict:
        if _QA_FILE.exists():
            return json.loads(_QA_FILE.read_text(encoding="utf-8"))
        return {}

    def _save_qa(self, qa: dict):
        _QA_FILE.parent.mkdir(parents=True, exist_ok=True)
        _QA_FILE.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")

    def _resolve_cached(self, question: str) -> str | None:
        qa = self._load_qa()
        key = _normalize_question(question)
        entry = qa.get(key)
        if entry is None:
            return None
        if isinstance(entry, dict):
            return entry.get("answer") or None
        return str(entry) if entry else None

    def _save_cached(self, question: str, answer: str, options: list | None = None):
        qa = self._load_qa()
        key = _normalize_question(question)
        if isinstance(qa.get(key), dict):
            qa[key]["answer"] = answer
        else:
            qa[key] = {"original": question, "answer": answer, "options": options} if options else answer
        self._save_qa(qa)

    # ── salary ───────────────────────────────────────────────────────────────

    async def _fill_salary(self, salary_value: int | str) -> bool:
        """Fill salary-only inputs — no question text, just a number field."""
        for sel in ["input[type='text'][aria-label*='salari']",
                     "input[aria-label*='salari']",
                     "input[type='text'][aria-label*='salary']",
                     "input[aria-label*='salary']",
                     "input[aria-label*='remuner']",
                     "input[placeholder*='salari']",
                     "input[placeholder*='salary']",
                     "input[placeholder*='remuner']"]:
            try:
                inp = self.page.locator(sel)
                if await inp.is_visible(timeout=1000):
                    await inp.fill(str(salary_value))
                    logger.info(f"Filled salary input: {salary_value}")
                    return True
            except Exception:
                pass
        return False

    async def _find_question_in_modal(self) -> str:
        try:
            modal = self.page.locator("[data-test-modal-container], [class*=artdeco-modal], [role='dialog']")
            spans = modal.locator("span, label, legend, p, div[class*=title], div[class*=heading]")
            count = await spans.count()
            texts = []
            for i in range(min(count, 20)):
                t = (await spans.nth(i).inner_text()).strip()
                if t:
                    texts.append(t)
            return " | ".join(texts)
        except Exception:
            return ""

    async def _extract_modal_options(self) -> list[str]:
        opts: list[str] = []
        modal = self.page.locator("[data-test-modal-container], [class*=artdeco-modal], [role='dialog']")
        for sel in ["select option", "input[type='radio']", "label", "span.radio-label"]:
            try:
                els = modal.locator(sel)
                count = await els.count()
                for i in range(count):
                    t = (await els.nth(i).inner_text()).strip()
                    val = await els.nth(i).get_attribute("value")
                    if t:
                        opts.append(t)
                    elif val:
                        opts.append(val)
            except Exception:
                pass
        if not opts:
            try:
                sel = modal.locator("select")
                if await sel.is_visible(timeout=500):
                    opts = await sel.locator("option").all_inner_texts()
            except Exception:
                pass
        return list(dict.fromkeys(o for o in opts if o))

    # ── main fill logic ──────────────────────────────────────────────────────

    async def _fill_field(self, el, question: str, job_title: str, job_description: str, salary_expectation: int | str):
        tag = await el.evaluate("el => el.tagName.toLowerCase()")
        label_text = question.lower()

        if any(k in label_text for k in SALARY_KEYWORDS):
            if salary_expectation:
                await self._fill_input(el, str(salary_expectation))
                logger.info(f"Filled salary with '{salary_expectation}'")
                return

        cached = self._resolve_cached(question)
        if cached:
            await self._fill_input(el, cached)
            logger.info(f"Filled '{question[:40]}' with cached: '{cached}'")
            return

        if tag == "select":
            options_list = await el.locator("option").all()
            option_values = []
            for opt in options_list:
                v = await opt.get_attribute("value")
                option_values.append(v)
            filtered = [v for v in option_values if v and v.strip()]
            if filtered:
                answer = await self._ask_llm(f"{question} (options: {filtered})", job_title, job_description)
                if answer and answer in option_values:
                    await el.select_option(value=answer)
                    self._save_cached(question, answer, options=filtered)
                    logger.info(f"LLM selected '{answer}' for '{question[:40]}'")
                    return
                elif filtered[0]:
                    await el.select_option(value=filtered[0])
                    logger.info(f"Selected default '{filtered[0]}' for '{question[:40]}'")
                    return
        else:
            answer = await self._ask_llm(question, job_title, job_description)
            if answer:
                await el.fill(answer)
                self._save_cached(question, answer)
                logger.info(f"LLM filled '{question[:40]}' with '{answer[:40]}'")
                return

    async def _fill_scope(self, scope, job_title: str, job_description: str, salary_expectation: int | str, visited_select_ids: set):
        # inputs
        inputs = await scope.locator("xpath=.//input[not(@type='hidden') and not(@type='radio') and not(@type='checkbox') and not(@type='submit') and not(@type='button') and not(@type='file')]").all()
        logger.info(f"Input elements found in scope: {len(inputs)}")
        for inp in inputs:
            if not await inp.is_visible():
                continue
            try:
                readonly = await inp.get_attribute("readonly")
                if readonly:
                    continue
                label_text = ""
                lid = await inp.get_attribute("id")
                if lid:
                    lbl = scope.locator(f"xpath=.//label[@for='{lid}']")
                    if await lbl.count():
                        label_text = (await lbl.first.inner_text()).strip()
                if not label_text:
                    aria = await inp.get_attribute("aria-label") or ""
                    ph = await inp.get_attribute("placeholder") or ""
                    label_text = aria or ph
                if not label_text:
                    continue
                await self._fill_field(inp, label_text, job_title, job_description, salary_expectation)
            except Exception as e:
                logger.warning(f"Input error: {e}")

        # textareas
        textareas = await scope.locator("xpath=.//textarea").all()
        logger.info(f"Textarea elements found in scope: {len(textareas)}")
        for ta in textareas:
            if not await ta.is_visible():
                continue
            try:
                readonly = await ta.get_attribute("readonly")
                if readonly:
                    continue
                label_text = ""
                tid = await ta.get_attribute("id")
                if tid:
                    lbl = scope.locator(f"xpath=.//label[@for='{tid}']")
                    if await lbl.count():
                        label_text = (await lbl.first.inner_text()).strip()
                if not label_text:
                    aria = await ta.get_attribute("aria-label") or ""
                    label_text = aria
                if not label_text:
                    continue
                cached = self._resolve_cached(label_text)
                if cached:
                    await ta.fill(cached)
                    logger.info(f"Filled textarea '{label_text[:30]}' with cached")
                else:
                    answer = await self._ask_llm(label_text, job_title, job_description)
                    if answer:
                        await ta.fill(answer)
                        self._save_cached(label_text, answer)
                        logger.info(f"LLM filled textarea '{label_text[:30]}'")
            except Exception as e:
                logger.warning(f"Textarea error: {e}")

        # selects
        selects = await scope.locator("xpath=.//select").all()
        logger.info(f"Select elements found in scope: {len(selects)}")
        for sel in selects:
            sel_id = await sel.get_attribute("id") or ""
            if sel_id in visited_select_ids:
                continue
            visited_select_ids.add(sel_id)
            if not await sel.is_visible():
                logger.warning(f"Select not displayed (hidden?): id={sel_id!r}")
                continue
            try:
                current_val = await sel.evaluate("el => el.value")
                logger.debug(f"Select shows current value '{current_val}'")
                if current_val and current_val != "" and current_val != "Select..." and current_val != "Selecione...":
                    logger.info(f"Select already filled (val={current_val!r}), skipping")
                    continue
                label_text = ""
                sid = sel_id
                if sid:
                    lbl = scope.locator(f"xpath=.//label[@for='{sid}']")
                    if await lbl.count():
                        label_text = (await lbl.first.inner_text()).strip()
                if not label_text:
                    aria = await sel.get_attribute("aria-label") or ""
                    label_text = aria
                if not label_text:
                    logger.warning(f"Select label unknown, skipping: id={sid!r}")
                    continue
                options = await sel.locator("option").all()
                option_values = []
                for opt in options:
                    v = await opt.get_attribute("value")
                    if v:
                        option_values.append(v)
                if not option_values:
                    logger.warning(f"Select has no options, skipping: id={sid!r}")
                    continue
                await self._fill_field(sel, label_text, job_title, job_description, salary_expectation)
            except Exception as e:
                logger.warning(f"Select error: {e}")

    # ── radio groups ─────────────────────────────────────────────────────────

    async def _fill_radio_groups(self, job_title: str, job_description: str):
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
            for group in groups:
                name = group["name"]
                label = group["label"]
                if not label:
                    continue
                logger.info(f"Radio group: '{label}'")
                els = self.page.locator(f"xpath=//input[@type='radio' and @name='{name}']")
                count = await els.count()
                if count == 0:
                    continue
                if count == 1:
                    await els.first.click()
                    logger.info(f"Clicked single radio for '{label}'")
                    continue
                cached = self._resolve_cached(label)
                if cached:
                    for i in range(count):
                        val = await els.nth(i).get_attribute("value")
                        lbl = await els.nth(i).evaluate("""el => {
                            const id = el.id;
                            if (id) {
                                const l = document.querySelector('label[for="'+id+'"]');
                                if (l) return l.innerText.trim();
                            }
                            return el.getAttribute('aria-label') || el.value;
                        }""")
                        if cached.lower() in [str(val or "").lower(), lbl.lower()]:
                            await els.nth(i).click()
                            logger.info(f"Selected cached radio '{cached}' for '{label}'")
                            break
                    else:
                        await els.first.click()
                        logger.info(f"Selected first radio for '{label}' (cache mismatch)")
                else:
                    labels = []
                    for i in range(count):
                        lbl = await els.nth(i).evaluate("""el => {
                            const id = el.id;
                            if (id) {
                                const l = document.querySelector('label[for="'+id+'"]');
                                if (l) return l.innerText.trim();
                            }
                            return el.getAttribute('aria-label') || el.value;
                        }""")
                        labels.append(lbl)
                    answer = await self._ask_llm(f"{label} (options: {labels})", job_title, job_description)
                    if answer:
                        for i in range(count):
                            lbl_text = labels[i] if i < len(labels) else ""
                            if answer.lower() in lbl_text.lower() or lbl_text.lower() in answer.lower():
                                await els.nth(i).click()
                                self._save_cached(label, lbl_text)
                                logger.info(f"LLM selected radio '{lbl_text}' for '{label}'")
                                break
                        else:
                            await els.first.click()
                            logger.info(f"Selected first radio for '{label}' (LLM no match)")
                    else:
                        await els.first.click()
                        logger.info(f"Selected default radio for '{label}'")
        except Exception as e:
            logger.warning(f"Radio fill error: {e}")

    # ── checkboxes ───────────────────────────────────────────────────────────

    async def _fill_checkboxes(self):
        try:
            cbs = self.page.locator("xpath=//input[@type='checkbox' and @required]")
            count = await cbs.count()
            for i in range(count):
                cb = cbs.nth(i)
                if not await cb.is_checked():
                    await cb.click()
                    logger.info("Checked required checkbox")
        except Exception:
            pass

    # ── remaining required fields ────────────────────────────────────────────

    async def _fill_remaining_required(self, job_title: str, job_description: str, salary_expectation: int | str):
        els = self.page.locator("xpath=//input[@required and @type!='hidden'] | //select[@required] | //textarea[@required]")
        count = await els.count()
        for i in range(count):
            el = els.nth(i)
            if not await el.is_visible():
                continue
            if not await self._is_unfilled(el):
                continue
            tag = await el.evaluate("el => el.tagName.toLowerCase()")
            label_text = ""
            eid = await el.get_attribute("id")
            if eid:
                lbl = self.page.locator(f"xpath=//label[@for='{eid}']")
                if await lbl.count():
                    label_text = (await lbl.first.inner_text()).strip()
            if not label_text:
                aria = await el.get_attribute("aria-label") or ""
                if aria:
                    label_text = aria
                else:
                    try:
                        parent = el.locator("xpath=..")
                        parent_text = (await parent.inner_text()).strip()
                        if parent_text:
                            label_text = parent_text
                    except Exception:
                        pass
                if not label_text:
                    try:
                        legend = await el.evaluate("""el => {
                            const p = el.closest('fieldset');
                            if (p) {
                                const leg = p.querySelector('legend');
                                if (leg) return leg.innerText.trim();
                            }
                            return '';
                        }""")
                        if legend:
                            label_text = legend
                    except Exception:
                        pass
            if not label_text:
                continue
            await self._fill_field(el, label_text, job_title, job_description, salary_expectation)

    async def _handle_radio_in_scope(self, scope):
        try:
            rid = await scope.get_attribute("id")
            lbl = scope.locator(f"xpath=.//label[@for='{rid}']")
            label_text = ""
            if await lbl.count():
                label_text = (await lbl.first.inner_text()).strip()
            if not label_text:
                legend = scope.locator("xpath=.//legend")
                if await legend.count():
                    label_text = (await legend.first.inner_text()).strip()
            if label_text:
                radio = self.page.locator(f"xpath=//input[@type='radio' and @id='{rid}']")
                if await radio.count():
                    await radio.first.click()
                    logger.info(f"Selected radio '{label_text}'")
        except Exception:
            pass

    # ── scroll to review ─────────────────────────────────────────────────────

    async def scroll_to_review(self):
        try:
            submit_btn = self.page.locator(
                "xpath=//button[contains(@aria-label,'Review') or contains(normalize-space(),'Review')]"
                " | button[class*=review]"
            )
            if await submit_btn.is_visible(timeout=3000):
                await submit_btn.scroll_into_view_if_needed()
                return
            btns = self.page.locator("button[type='submit']")
            if await btns.count():
                await btns.first.scroll_into_view_if_needed()
        except Exception:
            pass

    # ── select handler (React-aware) ─────────────────────────────────────────

    async def _handle_react_select(self, el, question: str, job_title: str, job_description: str, salary_expectation: int | str):
        # Approach 1: Playwright native select_option
        options = await el.locator("option").all()
        target_val = None
        target_label = ""
        for opt in options:
            v = await opt.get_attribute("value")
            t = (await opt.inner_text()).strip()
            if v and v.strip():
                target_val = v
                target_label = t
                break
        if not target_val:
            logger.warning("No selectable option found")
            return

        cached = self._resolve_cached(question)
        if cached:
            for opt in options:
                v = await opt.get_attribute("value")
                t = (await opt.inner_text()).strip()
                if cached.lower() in t.lower() or cached.lower() == v:
                    await el.select_option(value=v)
                    logger.info(f"Selected '{t}' for '{question[:40]}' (cached)")
                    return

        answer = await self._ask_llm(f"{question} (options: {[await o.inner_text() for o in options]})", job_title, job_description)
        if answer:
            for opt in options:
                t = (await opt.inner_text()).strip()
                if answer.lower() in t.lower() or t.lower() in answer.lower():
                    v = await opt.get_attribute("value")
                    await el.select_option(value=v)
                    self._save_cached(question, t)
                    logger.info(f"Selected '{t}' for '{question[:40]}' (LLM)")
                    return
        await el.select_option(value=target_val)
        logger.info(f"Selected default '{target_label}' for '{question[:40]}'")

    # ── error detection ──────────────────────────────────────────────────────

    async def _has_form_errors(self) -> bool:
        try:
            err = self.page.locator("[aria-describedby*='error'], [class*=error], [class*=feedback], [role='alert']")
            return await err.is_visible(timeout=1000)
        except Exception:
            return False

    # ── modal management ─────────────────────────────────────────────────────

    async def _get_modal(self):
        for sel in ["[data-test-modal-container]", "[class*=artdeco-modal]", "[role='dialog']"]:
            modal = self.page.locator(sel)
            if await modal.is_visible(timeout=1000):
                return modal
        return self.page.locator("body")

    async def _wait_for_modal(self, timeout: int = 15):
        for sel in ["[data-test-modal-container]", "[class*=artdeco-modal]", "[role='dialog']"]:
            try:
                await self.page.wait_for_selector(sel, timeout=timeout * 1000)
                return
            except Exception:
                pass

    async def _close_modal(self):
        try:
            close_btn = self.page.locator("button[aria-label='Dismiss'], button[aria-label='Close'], button[data-test-modal-close-btn]")
            if await close_btn.is_visible(timeout=2000):
                await close_btn.click()
                await self.page.wait_for_timeout(500)
                return
        except Exception:
            pass
        try:
            await self.page.keyboard.press("Escape")
            await self.page.wait_for_timeout(500)
        except Exception:
            pass

    async def _wait_for_modal_close(self, timeout: int = 10):
        for sel in ["[data-test-modal-container]", "[class*=artdeco-modal]", "[role='dialog']"]:
            try:
                await self.page.locator(sel).wait_for(state="hidden", timeout=timeout * 1000)
                return
            except Exception:
                pass

    # ── required check ───────────────────────────────────────────────────────

    async def _check_required_after_close(self) -> list[dict]:
        """Check for required fields after closing a modal section."""
        errors = []
        inputs = await self.page.locator("xpath=//input[@required and @type!='hidden'] | //select[@required] | //textarea[@required]").all()
        for inp in inputs:
            if not await inp.is_visible():
                continue
            if not await self._is_unfilled(inp):
                continue
            lid = await inp.get_attribute("id")
            label = ""
            if lid:
                lbl = self.page.locator(f"xpath=//label[@for='{lid}']")
                if await lbl.count():
                    label = (await lbl.first.inner_text()).strip()
            if not label:
                legend = await inp.evaluate("""el => {
                    const p = el.closest('fieldset');
                    if (p) {
                        const leg = p.querySelector('legend');
                        if (leg) return leg.innerText.trim();
                    }
                    return '';
                }""")
                if legend:
                    label = legend
            errors.append({"element": inp, "label": label or "unknown"})
        return errors

    async def _fill_errors(self, errors: list[dict], job_title: str, job_description: str, salary_expectation: int | str):
        for err in errors:
            el = err["element"]
            label = err["label"]
            try:
                tag = await el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "select":
                    options = await el.locator("option").all()
                    for opt in options:
                        v = await opt.get_attribute("value")
                        t = (await opt.inner_text()).strip()
                        if v and v.strip():
                            await el.select_option(value=v)
                            logger.info(f"Error-fix: selected '{t}' for '{label}'")
                            break
                else:
                    await self._fill_field(el, label, job_title, job_description, salary_expectation)
            except Exception as e:
                logger.warning(f"Error-fix failed for '{label}': {e}")

    # ── submit ───────────────────────────────────────────────────────────────

    async def submit_easy_apply(
        self,
        salary_expectation: int | str = "",
        job_title: str = "",
        job_description: str = "",
        no_submit: bool = False,
    ) -> bool:
        salary_filled = False
        visited_select_ids: set[str] = set()

        try:
            await self._wait_for_modal()
            max_steps = 30
            for step in range(max_steps):
                if no_submit:
                    break

                await self.page.wait_for_timeout(1500)

                # Fill salary
                if not salary_filled and salary_expectation:
                    salary_filled = await self._fill_salary(salary_expectation)

                modal = await self._get_modal()

                await self._fill_scope(modal, job_title, job_description, salary_expectation, visited_select_ids)
                await self._fill_radio_groups(job_title, job_description)
                await self._fill_checkboxes()
                await self._fill_remaining_required(job_title, job_description, salary_expectation)

                # Try Submit / Next / Review
                btn_selectors = [
                    "button[aria-label='Submit application']",
                    "button[aria-label='Enviar candidatura']",
                    "button[type='submit']",
                    "xpath=//button[contains(@aria-label,'Next') or contains(normalize-space(),'Next') or contains(normalize-space(),'Próximo') or contains(normalize-space(),'Proximo') or contains(normalize-space(),'Avançar')]",
                    "xpath=//button[contains(@aria-label,'Review') or contains(normalize-space(),'Review') or contains(normalize-space(),'Revisar')]",
                    "xpath=//button[contains(@aria-label,'Done') or contains(normalize-space(),'Done') or contains(normalize-space(),'Concluído')]",
                    "button[class*=artdeco-button--primary]",
                ]
                clicked = False
                for sel in btn_selectors:
                    try:
                        btn_type = "css" if not sel.startswith("xpath=") else "xpath"
                        loc = self.page.locator(sel[len("xpath="):] if sel.startswith("xpath=") else sel)
                        if await loc.is_visible(timeout=1000) and await loc.is_enabled():
                            btn_text = (await loc.inner_text()).strip().lower()
                            if "submit" in btn_text or "enviar" in btn_text:
                                logger.info(f"Submit button clicked: '{btn_text}'")
                                await loc.click()
                                await self.page.wait_for_timeout(2000)
                                return True
                            await loc.click()
                            clicked = True
                            logger.info(f"Clicked '{btn_text}' (step {step + 1})")
                            await self._wait_for_modal_close(timeout=3)
                            break
                    except Exception:
                        continue
                if not clicked:
                    logger.info(f"No more buttons to click (step {step + 1})")
                    break

            # Final submit check
            for sel in btn_selectors[:4]:
                try:
                    loc = self.page.locator(sel)
                    if await loc.is_visible(timeout=1000) and await loc.is_enabled():
                        btn_text = (await loc.inner_text()).strip().lower()
                        if "submit" in btn_text or "enviar" in btn_text or "send" in btn_text:
                            await loc.click()
                            logger.info("Final submit clicked")
                            await self.page.wait_for_timeout(2000)
                            return True
                except Exception:
                    pass
            return True
        except Exception as e:
            logger.error(f"Easy Apply error: {e}")
            return False

    # ── discard check ────────────────────────────────────────────────────────

    async def _has_discard_modal(self) -> bool:
        try:
            discard = self.page.locator(
                "xpath=//button[contains(@aria-label,'Discard') or contains(normalize-space(),'Discard') or contains(normalize-space(),'Descartar')]"
            )
            return await discard.is_visible(timeout=2000)
        except Exception:
            return False

    async def _close_discard(self):
        try:
            discard_btn = self.page.locator(
                "xpath=//button[contains(@aria-label,'Discard') or contains(normalize-space(),'Discard') or contains(normalize-space(),'Descartar')]"
            )
            if await discard_btn.is_visible(timeout=1000):
                await discard_btn.click()
                await self.page.wait_for_timeout(500)
        except Exception:
            await self.page.keyboard.press("Escape")
