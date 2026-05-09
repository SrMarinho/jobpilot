import asyncio
import os
import time
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support.select import Select
from selenium.common.exceptions import NoSuchElementException
from src.core.ai.llm_provider import get_llm_provider
from src.core.use_cases.job_application_handler import (
    _load_qa, _save_qa, _qa_answer, _qa_entry, _normalize_question,
)
from src.config.settings import logger

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


class IndeedApplicationHandler:
    MAX_STEPS = 10

    def __init__(self, driver: WebDriver, resume: str = ""):
        self.driver = driver
        self.resume = resume
        self._original_window = None

    def submit(self, salary_expectation: int | None = None, no_submit: bool = False) -> bool:
        try:
            self._original_window = self.driver.current_window_handle
            # Indeed may open application in a new tab
            WebDriverWait(self.driver, 5).until(lambda d: len(d.window_handles) > 1)
            new_window = [w for w in self.driver.window_handles if w != self._original_window][0]
            self.driver.switch_to.window(new_window)
            logger.info("Switched to Indeed application tab")
        except Exception:
            logger.info("Application opened in same tab")

        # URL guard: bail out if redirected to external ATS (Gupy, Greenhouse, Workday etc)
        time.sleep(1.5)
        cur_url = self.driver.current_url.lower()
        if not any(d in cur_url for d in ("smartapply.indeed.com", "indeed.com/apply", "indeed.com/viewjob")):
            logger.warning(f"Redirected to external ATS ({cur_url}) — aborting Indeed apply flow")
            try:
                if self._original_window and self.driver.current_window_handle != self._original_window:
                    self.driver.close()
            except Exception:
                pass
            self._return_to_main()
            return False

        try:
            for step in range(self.MAX_STEPS):
                self._wait_loading()

                self._scroll_bottom()
                self._select_default_radios()
                self._check_required_checkboxes()
                self._fill_all_fields(salary_expectation)
                self._scroll_bottom()

                if self._submit_visible():
                    if no_submit:
                        logger.info("[no-submit] Submit button reached — stopping before final click")
                        self._return_to_main()
                        return True
                    if not self._wait_submit_enabled():
                        logger.warning("Submit button never became enabled (reCAPTCHA blocked?)")
                        self._dump_buttons(step + 1)
                        self._return_to_main()
                        return False
                    if self._try_submit():
                        self._return_to_main()
                        return True

                if not self._click_next():
                    self._dump_fields(step + 1)
                    self._dump_buttons(step + 1)
                    self._dump_iframes(step + 1)
                    logger.warning(f"No actionable button on step {step + 1} — skipping")
                    self._return_to_main()
                    return False

            logger.warning("Exceeded max steps in Indeed application flow")
            self._return_to_main()
            return False

        except Exception as e:
            logger.error(f"Error during Indeed application: {e}")
            self._return_to_main()
            return False

    def _return_to_main(self):
        try:
            if self._original_window and self._original_window in self.driver.window_handles:
                self.driver.switch_to.window(self._original_window)
        except Exception:
            pass

    def _fill_all_fields(self, salary: int | None) -> None:
        try:
            inputs = self.driver.find_elements(
                By.XPATH,
                "//input[(@type='text' or @type='number' or @type='tel' or @type='email' or @type='url')]"
            )
            for inp in inputs:
                try:
                    if not inp.is_displayed() or inp.get_attribute("value") or inp.get_attribute("readonly"):
                        continue
                    question, required = self._get_field_label_required(inp)
                    answer = self._decide_answer(question, salary)
                    if answer:
                        self._set_input_value(inp, str(answer))
                        logger.info(f"Filled '{question}' -> '{answer}'")
                    elif required:
                        logger.warning(f"[required*] '{question}' sem resposta — preencha via 'answers set' ou complete manualmente")
                except Exception:
                    continue

            textareas = self.driver.find_elements(By.XPATH, "//textarea")
            for ta in textareas:
                try:
                    if not ta.is_displayed() or ta.get_attribute("value") or ta.get_attribute("readonly"):
                        continue
                    question, required = self._get_field_label_required(ta)
                    answer = self._qa_lookup(question)
                    if answer is None:
                        answer = self._ask_claude(question)
                        self._qa_store(question, answer, "textarea")
                    else:
                        logger.info(f"form_answers hit for '{question}'")
                    if answer:
                        ta.clear()
                        ta.send_keys(answer)
                        logger.info(f"Filled textarea '{question}'")
                    elif required:
                        logger.warning(f"[required*] textarea '{question}' sem resposta")
                except Exception:
                    continue

            selects = self.driver.find_elements(By.XPATH, "//select")
            for sel in selects:
                if not sel.is_displayed() or sel.get_attribute("value"):
                    continue
                question = self._get_field_label(sel)
                options = [o.text.strip() for o in Select(sel).options if o.get_attribute("value")]
                if not options:
                    continue
                cached = self._qa_lookup(question, options)
                if cached is not None:
                    answer = cached
                    logger.info(f"form_answers hit for '{question}' -> '{cached}'")
                else:
                    answer = self._ask_claude_choice(question, options)
                    self._qa_store(question, answer, "select", options)
                # Re-find element to avoid stale reference after AI call
                try:
                    fresh_els = self.driver.find_elements(By.XPATH, "//select[@required]")
                    for fresh in fresh_els:
                        if fresh.is_displayed() and self._get_field_label(fresh) == question:
                            sel = fresh
                            break
                except Exception:
                    pass
                try:
                    sel_obj = Select(sel)
                    if answer:
                        matched = next((o for o in options if o.lower() == answer.lower()), None)
                        matched = matched or next((o for o in options if answer.lower() in o.lower() or o.lower() in answer.lower()), None)
                        if matched:
                            sel_obj.select_by_visible_text(matched)
                            logger.info(f"Selected '{matched}' for '{question}'")
                        else:
                            # Fallback: first non-placeholder option
                            for opt_el in sel_obj.options:
                                if opt_el.get_attribute("value"):
                                    sel_obj.select_by_value(opt_el.get_attribute("value"))
                                    logger.warning(f"No match for '{answer}' in '{question}' — selected first option: '{opt_el.text.strip()}'")
                                    break
                except Exception as e:
                    logger.warning(f"Failed to select for '{question}': {e}")

        except Exception as e:
            logger.debug(f"Error filling fields: {e}")

    def _decide_answer(self, question: str, salary: int | None) -> str | None:
        if not question or question == "(unknown)":
            return None
        salary_keywords = [
            "salário", "salario", "salary", "remuneração", "remuneracao",
            "pretensão", "pretensao", "compensation", "salarial", "expectativa",
            "remuner", "wage", "pay ", "ctc",
        ]
        if salary and any(kw in question.lower() for kw in salary_keywords):
            return str(salary)
        cached = self._qa_lookup(question)
        if cached is not None:
            logger.info(f"form_answers hit for '{question}' -> '{cached}'")
            return cached
        ans = self._ask_claude(question)
        self._qa_store(question, ans, "text")
        return ans

    def _qa_context(self, max_entries: int = 25) -> str:
        try:
            qa = _load_qa()
            lines = []
            for entry in qa.values():
                if not isinstance(entry, dict):
                    continue
                q = entry.get("original") or ""
                a = (entry.get("answer") or "").strip()
                if q and a:
                    lines.append(f"- {q} → {a}")
                if len(lines) >= max_entries:
                    break
            return "\n".join(lines) if lines else "(nenhuma)"
        except Exception:
            return "(nenhuma)"

    def _qa_lookup(self, question: str, options: list[str] | None = None) -> str | None:
        qa = _load_qa()
        key = _normalize_question(question)
        entry = qa.get(key)
        if entry is None:
            return None
        ans = _qa_answer(entry)
        return ans or None

    def _qa_store(self, question: str, answer: str | None, field_type: str, options: list[str] | None = None) -> None:
        try:
            qa = _load_qa()
            key = _normalize_question(question)
            qa[key] = _qa_entry(answer or "", original=question, field_type=field_type, options=options)
            _save_qa(qa)
        except Exception as e:
            logger.debug(f"form_answers.json save failed: {e}")

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

    def _ask_claude(self, question: str) -> str | None:
        try:
            return asyncio.run(self._ask_claude_async(question))
        except Exception:
            return None

    def _ask_claude_choice(self, question: str, options: list[str]) -> str | None:
        try:
            return asyncio.run(self._ask_claude_choice_async(question, options))
        except Exception:
            return None

    async def _ask_claude_async(self, question: str) -> str | None:
        prompt = f"""Com base no currículo do candidato e em respostas anteriores, responda a seguinte pergunta do formulário de candidatura.

CURRÍCULO:
{self.resume}

RESPOSTAS ANTERIORES (use como contexto para inferir):
{self._qa_context()}

PERGUNTA: {question}

Responda APENAS com o valor — um número, palavra curta ou frase breve em português, adequado para um campo de formulário.
Se não souber e não puder inferir do currículo nem das respostas anteriores, responda exatamente: null
Não invente. Não inclua explicações ou pontuação."""

        result = (await get_llm_provider().complete(prompt) or "").strip()
        if not result or result.lower() == "null":
            return None
        return result

    async def _ask_claude_choice_async(self, question: str, options: list[str]) -> str | None:
        options_str = "\n".join(f"- {o}" for o in options)
        prompt = f"""Com base no currículo do candidato e em respostas anteriores, escolha a melhor opção.

CURRÍCULO:
{self.resume}

RESPOSTAS ANTERIORES (contexto):
{self._qa_context()}

PERGUNTA: {question}

OPÇÕES:
{options_str}

Responda APENAS com o texto exato da opção escolhida. Sem explicações."""

        result = await get_llm_provider().complete(prompt)

        for opt in options:
            if opt.lower() == result.lower():
                return opt
        for opt in options:
            if result.lower() in opt.lower() or opt.lower() in result.lower():
                return opt
        return None

    _SUBMIT_TEXTS = (
        "enviar candidatura", "submit application", "enviar", "submit",
        "send application", "candidatar-se", "apply now",
    )
    _NEXT_TEXTS = (
        "continuar", "continue", "próximo", "proximo", "next",
        "avançar", "avancar", "prosseguir", "continue applying",
        "review your application", "revisar candidatura", "revisar",
    )
    _SUBMIT_TESTIDS = ("submit", "ia-submit", "indeedapplybutton", "ia-submitbutton")
    _NEXT_TESTIDS = ("next", "continue", "ia-continue", "ia-continuebutton")

    def _find_clickable(self, texts: tuple[str, ...], testids: tuple[str, ...]):
        candidates = self.driver.find_elements(
            By.XPATH,
            "//button | //a[@role='button'] | //input[@type='submit' or @type='button']"
        )
        for el in candidates:
            try:
                if not el.is_displayed() or not el.is_enabled():
                    continue
                testid = (el.get_attribute("data-testid") or "").lower()
                label = (el.text or el.get_attribute("value") or el.get_attribute("aria-label") or "").strip().lower()
                if any(tid in testid for tid in testids):
                    return el
                if any(t in label for t in texts):
                    return el
            except Exception:
                continue
        return None

    def _submit_visible(self) -> bool:
        if self._find_clickable(self._SUBMIT_TEXTS, self._SUBMIT_TESTIDS):
            return True
        # Submit may exist but be disabled (reCAPTCHA / form validation pending) — still counts as "we reached review"
        return self._find_disabled_submit() is not None

    def _find_disabled_submit(self):
        for el in self.driver.find_elements(
            By.XPATH,
            "//button | //a[@role='button'] | //input[@type='submit' or @type='button']",
        ):
            try:
                if not el.is_displayed():
                    continue
                testid = (el.get_attribute("data-testid") or "").lower()
                label = (el.text or el.get_attribute("value") or el.get_attribute("aria-label") or "").strip().lower()
                if any(tid in testid for tid in self._SUBMIT_TESTIDS) or any(t in label for t in self._SUBMIT_TEXTS):
                    return el
            except Exception:
                continue
        return None

    def _scroll_to_captcha(self) -> None:
        try:
            for f in self.driver.find_elements(By.TAG_NAME, "iframe"):
                src = (f.get_attribute("src") or "").lower()
                title = (f.get_attribute("title") or "").lower()
                if "recaptcha" in src or "recaptcha" in title or "captcha" in title:
                    self.driver.execute_script(
                        "arguments[0].scrollIntoView({block:'center', inline:'center'});", f
                    )
                    time.sleep(0.4)
                    return
        except Exception:
            pass

    def _captcha_present(self) -> bool:
        try:
            for f in self.driver.find_elements(By.TAG_NAME, "iframe"):
                src = (f.get_attribute("src") or "").lower()
                title = (f.get_attribute("title") or "").lower()
                if "recaptcha" in src or "recaptcha" in title or "captcha" in title:
                    return True
        except Exception:
            pass
        return False

    def _wait_submit_enabled(
        self,
        timeout: int | None = None,
        manual_timeout: int | None = None,
    ) -> bool:
        if timeout is None:
            timeout = int(os.getenv("INDEED_SUBMIT_TIMEOUT", "30"))
        if manual_timeout is None:
            manual_timeout = int(os.getenv("INDEED_CAPTCHA_TIMEOUT", "15"))
        deadline = time.time() + timeout
        while time.time() < deadline:
            btn = self._find_clickable(self._SUBMIT_TEXTS, self._SUBMIT_TESTIDS)
            if btn:
                return True
            time.sleep(1)

        if not self._captcha_present():
            return False

        self._scroll_to_captcha()
        logger.warning(f"reCAPTCHA detected — switching to manual mode ({manual_timeout}s window)")
        print("\n" + "=" * 60)
        print(">>> reCAPTCHA: resolva o captcha na janela do navegador <<<")
        print(f">>> Aguardando até {manual_timeout}s para o submit habilitar... <<<")
        print("=" * 60 + "\n")
        deadline = time.time() + manual_timeout
        last_log = 0
        while time.time() < deadline:
            btn = self._find_clickable(self._SUBMIT_TEXTS, self._SUBMIT_TESTIDS)
            if btn:
                logger.info("Submit habilitou após captcha manual")
                return True
            remaining = int(deadline - time.time())
            if remaining <= last_log - 30 or last_log == 0:
                logger.info(f"Aguardando captcha... {remaining}s restantes")
                last_log = remaining
            time.sleep(2)
        logger.warning(f"Captcha timeout ({manual_timeout}s) — desistindo desta vaga")
        return False

    def _try_submit(self) -> bool:
        btn = self._find_clickable(self._SUBMIT_TEXTS, self._SUBMIT_TESTIDS)
        if not btn:
            return False
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            btn.click()
            logger.info("Application submitted on Indeed")
            time.sleep(2)
            return True
        except Exception as e:
            logger.warning(f"Submit click failed: {e}")
            return False

    def _click_next(self) -> bool:
        btn = self._find_clickable(self._NEXT_TEXTS, self._NEXT_TESTIDS)
        if not btn:
            return False
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            btn.click()
            return True
        except Exception as e:
            logger.warning(f"Next click failed: {e}")
            return False

    def _scroll_bottom(self) -> None:
        try:
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.5)
        except Exception:
            pass

    def _dump_iframes(self, step: int) -> None:
        try:
            iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
            entries = []
            for f in iframes:
                try:
                    entries.append(f"src='{(f.get_attribute('src') or '')[:80]}' id='{f.get_attribute('id') or ''}' title='{(f.get_attribute('title') or '')[:40]}'")
                except Exception:
                    continue
            if entries:
                logger.warning(f"[indeed step {step}] Iframes:\n  " + "\n  ".join(entries))
        except Exception:
            pass

    def _select_default_radios(self) -> None:
        try:
            groups: dict[str, list] = {}
            for r in self.driver.find_elements(By.XPATH, "//input[@type='radio']"):
                try:
                    if not r.is_displayed():
                        continue
                    name = r.get_attribute("name") or ""
                    groups.setdefault(name, []).append(r)
                except Exception:
                    continue
            for name, radios in groups.items():
                if any(r.is_selected() for r in radios):
                    continue
                try:
                    self.driver.execute_script("arguments[0].click();", radios[0])
                    label = self._get_field_label(radios[0]) or name
                    logger.info(f"Selected default radio for '{label}'")
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Radio default selection error: {e}")

    def _check_required_checkboxes(self) -> None:
        try:
            for cb in self.driver.find_elements(By.XPATH, "//input[@type='checkbox' and @required]"):
                try:
                    if cb.is_displayed() and not cb.is_selected():
                        self.driver.execute_script("arguments[0].click();", cb)
                except Exception:
                    continue
        except Exception:
            pass

    def _dump_fields(self, step: int) -> None:
        try:
            entries = []
            for el in self.driver.find_elements(By.XPATH, "//input | //select | //textarea"):
                try:
                    if not el.is_displayed():
                        continue
                    tag = el.tag_name
                    typ = el.get_attribute("type") or ""
                    name = el.get_attribute("name") or ""
                    el_id = el.get_attribute("id") or ""
                    req = el.get_attribute("required") is not None or el.get_attribute("aria-required") == "true"
                    val = (el.get_attribute("value") or "")[:40]
                    label = self._get_field_label(el)[:40]
                    entries.append(f"{tag}[type={typ}] id='{el_id}' name='{name}' req={req} val='{val}' label='{label}'")
                except Exception:
                    continue
            logger.warning(f"[indeed step {step}] Visible fields:\n  " + "\n  ".join(entries) if entries else f"[indeed step {step}] No visible fields")
        except Exception as e:
            logger.debug(f"Field dump error: {e}")

    def _dump_buttons(self, step: int) -> None:
        try:
            els = self.driver.find_elements(
                By.XPATH,
                "//button | //a[@role='button'] | //input[@type='submit' or @type='button']"
            )
            entries = []
            for el in els:
                try:
                    if not el.is_displayed():
                        continue
                    text = (el.text or el.get_attribute("value") or "").strip()[:60]
                    testid = el.get_attribute("data-testid") or ""
                    aria = (el.get_attribute("aria-label") or "")[:60]
                    cls = (el.get_attribute("class") or "")[:80]
                    typ = el.get_attribute("type") or ""
                    enabled = el.is_enabled()
                    entries.append(f"text='{text}' aria='{aria}' type='{typ}' testid='{testid}' class='{cls}' enabled={enabled}")
                except Exception:
                    continue
            logger.warning(f"[indeed step {step}] Visible buttons:\n  " + "\n  ".join(entries) if entries else f"[indeed step {step}] No visible buttons")
            logger.warning(f"[indeed step {step}] URL: {self.driver.current_url}")
        except Exception as e:
            logger.debug(f"Button dump error: {e}")

    # Indeed-specific known fields → friendly question keys (matches form_answers.json entries)
    _INDEED_FIELD_KEYS = {
        "location-postal-code": "Código postal (CEP)",
        "location-locality":    "Cidade, estado",
        "location-address":     "Endereço",
        "location-country":     "País",
    }

    def _get_field_label(self, element) -> str:
        label, _ = self._get_field_label_required(element)
        return label

    def _get_field_label_required(self, element) -> tuple[str, bool]:
        """Return (clean_label, is_required). Required if label ends with '*' or @required attr set."""
        try:
            raw = ""
            field_id = element.get_attribute("id")
            if field_id:
                labels = self.driver.find_elements(By.XPATH, f"//label[@for='{field_id}']")
                if labels:
                    raw = labels[0].text.strip()
            if not raw:
                name = (element.get_attribute("name") or "").strip()
                if name in self._INDEED_FIELD_KEYS:
                    raw = self._INDEED_FIELD_KEYS[name]
            if not raw:
                raw = (element.get_attribute("placeholder") or "").strip()
            if not raw:
                raw = (element.get_attribute("aria-label") or "").strip()

            star_required = raw.endswith("*")
            attr_required = (
                element.get_attribute("required") is not None
                or element.get_attribute("aria-required") == "true"
            )
            clean = raw.rstrip("*").strip(" :") if raw else ""
            return (clean or "(unknown)", star_required or attr_required)
        except Exception:
            return ("(unknown)", False)

    def _wait_loading(self, timeout: int = 10) -> None:
        """Wait for Indeed Smart Apply loading spinner / route transition."""
        time.sleep(0.6)
        try:
            WebDriverWait(self.driver, timeout).until_not(
                lambda d: any(
                    e.is_displayed()
                    for e in d.find_elements(
                        By.CSS_SELECTOR,
                        "[class*=Spinner],[class*=spinner],[class*=Loading],[class*=loading],[class*=Skeleton],[role=progressbar]",
                    )
                )
            )
        except Exception:
            pass
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except Exception:
            pass
        time.sleep(0.5)
