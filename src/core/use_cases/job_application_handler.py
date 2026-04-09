import json
import asyncio
import time
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.select import Select
from selenium.common.exceptions import NoSuchElementException
from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage
from src.config.settings import logger

HAIKU_MODEL = "claude-haiku-4-5-20251001"
SALARY_KEYWORDS = ["salário", "salario", "salary", "remuneração", "pretensão", "compensation"]

# React-aware value setter — triggers React's synthetic onChange
_REACT_SET_VALUE = """
(function(el, val) {
    var setter = Object.getOwnPropertyDescriptor(el.constructor.prototype, 'value');
    if (setter && setter.set) {
        setter.set.call(el, val);
    } else {
        el.value = val;
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
})(arguments[0], arguments[1]);
"""


class JobApplicationHandler:
    MAX_STEPS = 10

    def __init__(self, driver: WebDriver, resume: str = ""):
        self.driver = driver
        self.resume = resume

    def submit_easy_apply(self, salary_expectation: int | None = None) -> bool:
        try:
            for step in range(self.MAX_STEPS):
                time.sleep(1.5)

                self._fill_all_fields(salary_expectation)

                if self._has_unanswered_required_fields():
                    logger.warning("Required fields not filled — skipping")
                    self._close_modal()
                    return False

                if self._try_submit():
                    return True

                if not self._click_next():
                    logger.warning(f"No actionable button on step {step + 1} — skipping")
                    self._close_modal()
                    return False

            logger.warning("Exceeded max steps in Easy Apply flow")
            self._close_modal()
            return False

        except Exception as e:
            logger.error(f"Error during Easy Apply: {e}")
            self._close_modal()
            return False

    # ── field filling ────────────────────────────────────────────────────────

    def _fill_all_fields(self, salary: int | None) -> None:
        """Collect all unfilled required fields and answer them in a single Claude call."""
        try:
            fields = []  # list of {"el": element, "question": str, "type": "text"|"choice", "options": list}

            inputs = self.driver.find_elements(
                By.XPATH,
                "//input[@required and @type!='hidden' and (@type='text' or @type='number' or @type='tel')]"
            )
            for inp in inputs:
                if not inp.is_displayed() or inp.get_attribute("value"):
                    continue
                question = self._get_field_label(inp)
                if not question or question == "(unknown)":
                    continue
                if salary and any(kw in question.lower() for kw in SALARY_KEYWORDS):
                    self._set_input_value(inp, str(salary))
                    logger.info(f"Filled '{question}' → '{salary}' (salary)")
                    continue
                fields.append({"el": inp, "question": question, "type": "text", "options": []})

            # Find all visible selects — with or without @required
            selects = self.driver.find_elements(By.XPATH, "//select")
            for sel in selects:
                if not sel.is_displayed():
                    continue
                current_val = sel.get_attribute("value") or ""
                options_els = Select(sel).options
                # Skip if already has a meaningful selection (not the placeholder/first empty option)
                non_empty_vals = [o.get_attribute("value") for o in options_els if o.get_attribute("value")]
                if current_val and current_val in non_empty_vals:
                    continue
                question = self._get_field_label(sel)
                if not question or question == "(unknown)":
                    continue
                options = [o.text.strip() for o in options_els if o.get_attribute("value")]
                if not options:
                    continue
                fields.append({"el": sel, "question": question, "type": "choice", "options": options})

            if not fields:
                return

            answers = asyncio.run(self._batch_answer(fields))

            for i, field in enumerate(fields):
                answer = answers.get(str(i))
                if not answer:
                    continue
                if field["type"] == "text":
                    self._set_input_value(field["el"], str(answer))
                    logger.info(f"Filled '{field['question']}' → '{answer}'")
                else:
                    matched = self._match_option(answer, field["options"])
                    if matched:
                        try:
                            Select(field["el"]).select_by_visible_text(matched)
                            logger.info(f"Selected '{matched}' for '{field['question']}'")
                        except Exception as e:
                            logger.warning(f"Failed to select '{matched}' for '{field['question']}': {e}")
                    else:
                        logger.warning(f"No option matched '{answer}' for '{field['question']}' — options: {field['options']}")

        except Exception as e:
            logger.debug(f"Error filling fields: {e}")

    async def _batch_answer(self, fields: list[dict]) -> dict:
        """Send all form questions to Claude in one call. Returns {index: answer}."""
        questions_str = ""
        for i, f in enumerate(fields):
            if f["type"] == "text":
                questions_str += f"{i}. {f['question']} (text)\n"
            else:
                opts = ", ".join(f["options"])
                questions_str += f"{i}. {f['question']} (choose from: {opts})\n"

        prompt = f"""Based on this candidate's resume, answer ALL the following job application form questions.

RESUME:
{self.resume}

QUESTIONS:
{questions_str}
Reply with ONLY a JSON object mapping each question number (as string) to its answer.
For text fields: reply with a short value (number, word, or brief phrase).
For choice fields: reply with the exact text of the chosen option.
Example: {{"0": "3", "1": "Intermediário", "2": "Não"}}"""

        result = ""
        async for message in query(prompt=prompt, options=ClaudeAgentOptions(max_turns=1, model=HAIKU_MODEL)):
            if isinstance(message, ResultMessage):
                result = message.result.strip()

        try:
            import re
            match = re.search(r"\{.*\}", result, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return {}

    def _match_option(self, answer: str, options: list[str]) -> str | None:
        """Find the best matching option for a given answer string."""
        import unicodedata

        def normalize(s: str) -> str:
            s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
            return s.lower().strip()

        answer_n = normalize(answer)

        # 1. Exact match (normalized)
        for opt in options:
            if normalize(opt) == answer_n:
                return opt

        # 2. Answer contains option or option contains answer
        for opt in options:
            opt_n = normalize(opt)
            if answer_n in opt_n or opt_n in answer_n:
                return opt

        # 3. Any word from answer matches any word in option
        answer_words = set(answer_n.split())
        for opt in options:
            opt_words = set(normalize(opt).split())
            if answer_words & opt_words:
                return opt

        return None

    def _set_input_value(self, element, value: str) -> None:
        try:
            self.driver.execute_script(_REACT_SET_VALUE, element, value)
            time.sleep(0.2)
        except Exception:
            try:
                element.clear()
                element.send_keys(value)
            except Exception:
                pass

    # ── form navigation ──────────────────────────────────────────────────────

    def _click_btn(self, btn) -> bool:
        try:
            btn.click()
            return True
        except Exception:
            try:
                self.driver.execute_script("arguments[0].click();", btn)
                return True
            except Exception:
                return False

    def _try_submit(self) -> bool:
        try:
            btn = self.driver.find_element(
                By.XPATH,
                "//button["
                "contains(@aria-label,'Submit application') or "
                "contains(@aria-label,'Enviar candidatura') or "
                ".//span[normalize-space()='Submit application'] or "
                ".//span[normalize-space()='Enviar candidatura']"
                "]",
            )
            if self._click_btn(btn):
                logger.info("Application submitted")
                time.sleep(1.5)
                self._close_modal()
                return True
        except NoSuchElementException:
            pass
        return False

    def _click_next(self) -> bool:
        try:
            btn = self.driver.find_element(
                By.XPATH,
                "//button["
                "contains(@aria-label,'Continue to next step') or "
                "contains(@aria-label,'Continuar para') or "
                "contains(@aria-label,'Avançar para') or "
                "contains(@aria-label,'Review your application') or "
                "contains(@aria-label,'Revisar') or "
                ".//span[normalize-space()='Next'] or "
                ".//span[normalize-space()='Próximo'] or "
                ".//span[normalize-space()='Avançar'] or "
                ".//span[normalize-space()='Review'] or "
                ".//span[normalize-space()='Revisar']"
                "]",
            )
            return self._click_btn(btn)
        except NoSuchElementException:
            pass
        return False

    # ── validation ───────────────────────────────────────────────────────────

    def _has_unanswered_required_fields(self) -> bool:
        try:
            inputs = self.driver.find_elements(
                By.XPATH, "//input[@required and @type!='hidden']"
            )
            for inp in inputs:
                if inp.is_displayed() and not inp.get_attribute("value"):
                    label = self._get_field_label(inp)
                    logger.warning(f"Unfilled required input: '{label}'")
                    return True

            selects = self.driver.find_elements(By.XPATH, "//select[@required]")
            for sel in selects:
                if sel.is_displayed() and not sel.get_attribute("value"):
                    label = self._get_field_label(sel)
                    logger.warning(f"Unfilled required select: '{label}'")
                    return True
        except Exception:
            pass
        return False

    def _get_field_label(self, element) -> str:
        try:
            field_id = element.get_attribute("id")
            if field_id:
                labels = self.driver.find_elements(By.XPATH, f"//label[@for='{field_id}']")
                if labels:
                    return labels[0].text.strip()
            placeholder = element.get_attribute("placeholder") or ""
            aria_label = element.get_attribute("aria-label") or ""
            return placeholder or aria_label or "(unknown)"
        except Exception:
            return "(unknown)"

    # ── modal control ─────────────────────────────────────────────────────────

    def _close_modal(self) -> None:
        try:
            btn = self.driver.find_element(
                By.XPATH,
                "//button["
                "@aria-label='Dismiss' or "
                "@aria-label='Fechar' or "
                "contains(@class,'artdeco-modal__dismiss')"
                "]",
            )
            btn.click()
            time.sleep(0.5)

            try:
                discard_btn = self.driver.find_element(
                    By.XPATH,
                    "//button["
                    ".//span[normalize-space()='Discard'] or "
                    ".//span[normalize-space()='Descartar']"
                    "]",
                )
                discard_btn.click()
            except Exception:
                pass

        except Exception:
            try:
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                time.sleep(0.5)
            except Exception:
                pass
