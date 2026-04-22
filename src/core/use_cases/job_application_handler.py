import json
import unicodedata
import asyncio
import time
import os
from pathlib import Path
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.select import Select
from selenium.common.exceptions import NoSuchElementException
from src.core.ai.llm_provider import get_llm_provider
from src.config.settings import logger

SALARY_KEYWORDS = [
    "salário", "salario", "salary", "remuneração", "remuneracao",
    "pretensão", "pretensao", "compensation", "salarial", "expectativa",
    "remuner", "wage", "pay ", "ctc",
]

_QA_FILE = Path(__file__).parent.parent.parent.parent / "files" / "qa.json"


def _normalize(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()

def _normalize_question(q: str) -> str:
    """Normalize question string for use as a stable dict key."""
    return " ".join(_normalize(q).split())


def _load_qa() -> dict:
    try:
        if _QA_FILE.exists():
            with open(_QA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _save_qa(qa: dict) -> None:
    try:
        _QA_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_QA_FILE, "w", encoding="utf-8") as f:
            json.dump(qa, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Could not save qa.json: {e}")


def _qa_answer(entry) -> str:
    """Extract the answer string from a qa entry (supports legacy string format and new dict format)."""
    if isinstance(entry, dict):
        return entry.get("answer", "") or ""
    return str(entry) if entry is not None else ""


def _qa_entry(answer: str, original: str = "", field_type: str = "text", options: list | None = None) -> dict:
    """Build a rich qa entry dict."""
    return {"answer": answer, "original": original, "type": field_type, "options": options}

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
        self.job_title = ""
        self.job_description = ""

    def submit_easy_apply(
        self,
        salary_expectation: int | None = None,
        job_title: str = "",
        job_description: str = "",
    ) -> bool:
        self.job_title = job_title
        self.job_description = job_description[:1500]
        try:
            for step in range(self.MAX_STEPS):
                time.sleep(1.5)

                if step == 0 and self._form_is_spanish():
                    logger.warning("Form is in Spanish — skipping application")
                    self._close_modal()
                    return False

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

    _ES_FORM_MARKERS = {"¿", "ñ", "años", "experiencia", "cuántos", "cuantos",
                        "seleccionado", "comenzar", "trabajar", "empresa"}

    def _form_is_spanish(self) -> bool:
        try:
            modal = self._get_modal()
            text = (modal or self.driver).text.lower()
            hits = sum(1 for m in self._ES_FORM_MARKERS if m in text)
            return hits >= 2
        except Exception:
            return False

    def _get_modal(self):
        """Return the Easy Apply modal element, or None if not found."""
        for selector in [
            "//div[contains(@class,'jobs-easy-apply-modal')]",
            "//div[contains(@class,'artdeco-modal') and .//*[contains(@class,'jobs-easy-apply')]]",
            "//div[@role='dialog' and .//*[contains(@aria-label,'apply') or contains(@aria-label,'Apply') or contains(@aria-label,'candidatura')]]",
            "//div[@role='dialog']",
        ]:
            try:
                els = self.driver.find_elements(By.XPATH, selector)
                if els:
                    return els[0]
            except Exception:
                continue
        return None

    def _fill_all_fields(self, salary: int | None) -> None:
        """Collect all unfilled required fields and answer them in a single AI call."""
        try:
            fields = []  # list of {"el": element, "question": str, "type": "text"|"choice"|"radio"|"checkbox"|"textarea", "options": list}

            modal = self._get_modal()
            scope = modal or self.driver  # fall back to full page if modal not found
            if modal:
                logger.debug("Scoping field search to Easy Apply modal")
            else:
                logger.debug("Modal not found — searching full page")

            # ── text / number / tel inputs (all visible, not just @required) ──
            inputs = scope.find_elements(
                By.XPATH,
                ".//input[@type!='hidden' and (@type='text' or @type='number' or @type='tel')]"
            )
            for inp in inputs:
                if not inp.is_displayed():
                    continue
                current_val = (inp.get_attribute("value") or "").strip()
                error = self._get_field_error(inp)
                # Skip if already filled and no validation error
                if current_val and not error:
                    continue
                question = self._get_field_label(inp)
                if not question or question == "(unknown)":
                    continue
                if salary and any(kw in question.lower() for kw in SALARY_KEYWORDS):
                    self._set_input_value(inp, str(salary))
                    logger.info(f"Filled '{question}' → '{salary}' (salary)")
                    continue
                fields.append({
                    "el": inp,
                    "question": question,
                    "type": "text",
                    "options": [],
                    "current_value": current_val,
                    "error": error,
                })

            # ── textareas ─────────────────────────────────────────────────────
            textareas = scope.find_elements(By.XPATH, ".//textarea")
            for ta in textareas:
                if not ta.is_displayed():
                    continue
                current_val = (ta.get_attribute("value") or "").strip()
                error = self._get_field_error(ta)
                if current_val and not error:
                    continue
                question = self._get_field_label(ta)
                if not question or question == "(unknown)":
                    continue
                fields.append({
                    "el": ta,
                    "question": question,
                    "type": "textarea",
                    "options": [],
                    "current_value": current_val,
                    "error": error,
                })

            # ── select dropdowns ──────────────────────────────────────────────
            selects = scope.find_elements(By.XPATH, ".//select")
            for sel in selects:
                try:
                    if not sel.is_displayed():
                        continue
                    sel_data = self.driver.execute_script(
                        "var s=arguments[0]; return {val:s.value,"
                        "opts:Array.from(s.options).map(o=>({v:o.value,t:o.text.trim()}))}",
                        sel
                    )
                    current_val = sel_data["val"] or ""
                    non_empty = [o for o in sel_data["opts"] if o["v"]]
                    if current_val and any(o["v"] == current_val for o in non_empty):
                        continue
                    question = self._get_field_label(sel)
                    if not question or question == "(unknown)":
                        continue
                    option_labels = [o["t"] for o in non_empty]
                    if not option_labels:
                        continue
                    fields.append({"el": sel, "question": question, "type": "choice", "options": option_labels, "_option_map": {o["t"]: o["v"] for o in non_empty}, "error": None, "current_value": ""})
                except Exception:
                    continue

            # ── radio button groups ───────────────────────────────────────────
            radio_script = """
                var root = arguments[0] || document;
                var inputs = root.querySelectorAll('input[type="radio"]');
                var groups = {};
                inputs.forEach(function(r) {
                    if (!r.offsetParent) return;
                    var name = r.name || r.id || '';
                    if (!name) return;
                    if (!groups[name]) groups[name] = [];
                    var id = r.id || '';
                    var lbl = '';
                    if (id) { var l = document.querySelector('label[for="'+id+'"]'); if (l) lbl = l.innerText.trim(); }
                    if (!lbl) lbl = r.value || '';
                    groups[name].push({id: r.id, name: r.name, value: r.value, label: lbl, checked: r.checked});
                });
                return groups;
            """
            radio_groups = self.driver.execute_script(radio_script, modal)
            for group_name, radios_data in (radio_groups or {}).items():
                if any(r["checked"] for r in radios_data):
                    continue
                options = [r["label"] or r["value"] for r in radios_data if r["label"] or r["value"]]
                if not options:
                    continue
                # Get the DOM elements fresh for clicking later
                group_els = self.driver.find_elements(By.XPATH, f"//input[@type='radio' and @name='{group_name}']")
                if not group_els:
                    continue
                question = self._get_radio_group_label(group_els) or self._get_field_label(group_els[0])
                if not question or question == "(unknown)":
                    continue
                fields.append({"el": group_els, "question": question, "type": "radio", "options": options, "_radio_data": radios_data, "error": None, "current_value": ""})

            # ── checkboxes ────────────────────────────────────────────────────
            checkboxes = scope.find_elements(By.XPATH, ".//input[@type='checkbox']")
            for chk in checkboxes:
                if not chk.is_displayed() or chk.is_selected():
                    continue
                question = self._get_field_label(chk)
                if not question or question == "(unknown)":
                    continue
                fields.append({"el": chk, "question": question, "type": "checkbox", "options": ["Yes", "No"], "error": None, "current_value": ""})

            if not fields:
                logger.debug("No unfilled fields found on this step")
                return

            logger.info(f"Fields found: {[f['question'] + ' (' + f['type'] + ')' for f in fields]}")
            qa = _load_qa()

            # Resolve fields from cache first; collect remaining for AI
            cached_answers: dict[str, str] = {}
            pending_fields: list[dict] = []
            pending_indices: list[int] = []

            for i, field in enumerate(fields):
                key = _normalize_question(field["question"])
                saved_answer = _qa_answer(qa.get(key))
                if saved_answer:
                    cached_answers[str(i)] = saved_answer
                else:
                    pending_fields.append(field)
                    pending_indices.append(i)

            # Single AI call only for fields without cached answers
            ai_answers: dict[str, str] = {}
            if pending_fields:
                raw = asyncio.run(self._batch_answer(pending_fields))
                # remap local indices back to original indices
                _NULL_WORDS = {"null", "nulo", "nenhum", "nenhuma", "none", "n/a", "não sei", "nao sei", "desconhecido", "sem experiencia", "sem experiência"}
                for local_i, orig_i in enumerate(pending_indices):
                    val = raw.get(str(local_i))
                    # null or empty = LLM doesn't know, skip (will be saved for manual input)
                    if val is not None and str(val).strip() and str(val).strip().lower() not in _NULL_WORDS:
                        ai_answers[str(orig_i)] = str(val)

            answers = {**cached_answers, **ai_answers}

            # Save unanswered questions to qa.json so user can fill them manually
            for i, field in enumerate(fields):
                if answers.get(str(i)):
                    continue
                key = _normalize_question(field["question"])
                if key not in qa:
                    qa[key] = _qa_entry("", field["question"], field["type"], field.get("options"))
                    _save_qa(qa)
                    logger.warning(f"No answer for '{field['question']}' — saved to qa.json for manual input")

            # Apply answers and validate; retry with AI on validation errors
            for i, field in enumerate(fields):
                answer = answers.get(str(i))
                if not answer:
                    continue

                key = _normalize_question(field["question"])

                if field["type"] in ("text", "textarea"):
                    self._set_input_value(field["el"], str(answer))
                    time.sleep(0.4)
                    error = self._get_field_error(field["el"])
                    if error:
                        logger.warning(f"Validation error for '{field['question']}' (answer='{answer}'): {error}")
                        corrected = asyncio.run(self._retry_answer(field["question"], answer, error))
                        if corrected:
                            self._set_input_value(field["el"], corrected)
                            logger.info(f"Corrected '{field['question']}' → '{corrected}'")
                            answer = corrected
                        else:
                            logger.warning(f"Could not correct '{field['question']}' — leaving as is")
                    else:
                        logger.info(f"Filled '{field['question']}' → '{answer}'")
                elif field["type"] == "radio":
                    self._apply_radio(field, answer)
                elif field["type"] == "checkbox":
                    self._apply_checkbox(field, answer)
                else:
                    self._apply_select(field, answer)

                if _qa_answer(qa.get(key)) != answer:
                    qa[key] = _qa_entry(answer, field["question"], field["type"], field.get("options"))
                    _save_qa(qa)

            # ── post-fill validation pass ─────────────────────────────────────
            # Collect all inputs still marked invalid after filling, fix in one AI call
            time.sleep(0.5)
            invalid_fields = []
            for field in fields:
                if field["type"] not in ("text", "textarea"):
                    continue
                el = field["el"]
                try:
                    error = self._get_field_error(el)
                    if error:
                        current_val = (el.get_attribute("value") or "").strip()
                        invalid_fields.append({"field": field, "bad_answer": current_val, "error": error})
                except Exception:
                    continue

            if invalid_fields:
                logger.warning(f"Post-fill: {len(invalid_fields)} field(s) still invalid — asking AI to correct")
                corrections = asyncio.run(self._batch_correct(invalid_fields))
                for item in invalid_fields:
                    q = item["field"]["question"]
                    corrected = corrections.get(_normalize_question(q))
                    if corrected:
                        self._set_input_value(item["field"]["el"], corrected)
                        logger.info(f"Post-fill corrected '{q}' → '{corrected}'")
                        key = _normalize_question(q)
                        qa[key] = _qa_entry(corrected, q, item["field"]["type"], item["field"].get("options"))
                        _save_qa(qa)

        except Exception as e:
            import traceback
            logger.warning(f"Error filling fields: {e}\n{traceback.format_exc()}")

    def _get_field_error(self, element) -> str | None:
        """Returns the validation error message for a field, or None if valid."""
        try:
            if element.get_attribute("aria-invalid") != "true":
                return None
            described_by = element.get_attribute("aria-describedby") or ""
            for eid in described_by.split():
                try:
                    err_el = self.driver.find_element(By.ID, eid)
                    text = err_el.text.strip()
                    if text:
                        return text
                except Exception:
                    pass
            # Fallback: look for nearby error element
            try:
                parent = self.driver.execute_script("return arguments[0].parentElement;", element)
                if parent:
                    err = parent.find_element(By.XPATH, ".//*[contains(@class,'error') or contains(@class,'feedback')]")
                    text = err.text.strip()
                    if text:
                        return text
            except Exception:
                pass
            return "Invalid value"
        except Exception:
            return None

    async def _batch_correct(self, invalid_fields: list[dict]) -> dict:
        """Ask AI to correct multiple invalid fields in one call. Returns {normalized_question: corrected_value}."""
        items_str = ""
        for i, item in enumerate(invalid_fields):
            items_str += (
                f"{i}. PERGUNTA: {item['field']['question']}\n"
                f"   RESPOSTA ERRADA: {item['bad_answer']}\n"
                f"   ERRO: {item['error']}\n\n"
            )

        job_context = ""
        if self.job_title:
            job_context = f"\nVAGA: {self.job_title}\n"
        if self.job_description:
            job_context += f"DESCRIÇÃO DA VAGA:\n{self.job_description}\n"

        prompt = f"""Você preencheu campos de um formulário de candidatura mas alguns falharam na validação.

CURRÍCULO DO CANDIDATO:
{self.resume}
{job_context}
CAMPOS COM ERRO:
{items_str}
Para cada campo, forneça uma resposta corrigida que satisfaça a validação.
Responda APENAS com um objeto JSON mapeando o número do campo (como string) para a resposta corrigida.
Dicas: se o erro indica "número", responda só com dígitos. Se indica "obrigatório", responda algo curto e relevante usando o contexto da vaga.
Exemplo: {{"0": "6000", "1": "3"}}"""

        result = await get_llm_provider().complete(prompt)
        logger.info(f"Batch correct raw: {result!r}")

        try:
            import re
            match = re.search(r"\{.*\}", result, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                # Remap from index to normalized question key
                return {
                    _normalize_question(invalid_fields[int(k)]["field"]["question"]): v
                    for k, v in parsed.items()
                    if k.isdigit() and int(k) < len(invalid_fields)
                }
        except Exception as e:
            logger.warning(f"Failed to parse batch correct response: {e}")
        return {}

    async def _retry_answer(self, question: str, bad_answer: str, error: str) -> str | None:
        """Ask LLM to correct an answer that failed field validation."""
        job_context = ""
        if self.job_title:
            job_context = f"\nVAGA: {self.job_title}\n"
        if self.job_description:
            job_context += f"DESCRIÇÃO DA VAGA:\n{self.job_description}\n"

        prompt = f"""Você preencheu um campo de formulário de candidatura mas recebeu um erro de validação.

CURRÍCULO DO CANDIDATO:
{self.resume}
{job_context}
PERGUNTA: {question}
SUA RESPOSTA ANTERIOR: {bad_answer}
ERRO DE VALIDAÇÃO: {error}

Forneça uma resposta corrigida que satisfaça o requisito de validação.
Responda APENAS com o valor corrigido — um número, palavra curta ou frase breve em português. Sem explicações."""
        try:
            result = await get_llm_provider().complete(prompt)
            return result.strip() if result else None
        except Exception:
            return None

    def _get_radio_group_label(self, group: list) -> str | None:
        """Try to find the fieldset legend or nearest group label for a radio group."""
        try:
            el = group[0]
            # Walk up looking for fieldset > legend
            script = """
                var el = arguments[0];
                for (var i = 0; i < 5; i++) {
                    el = el.parentElement;
                    if (!el) break;
                    if (el.tagName === 'FIELDSET') {
                        var leg = el.querySelector('legend');
                        return leg ? leg.innerText.trim() : null;
                    }
                }
                return null;
            """
            result = self.driver.execute_script(script, el)
            return result or None
        except Exception:
            return None

    def _apply_radio(self, field: dict, answer: str) -> None:
        """Click the radio button whose label best matches the answer."""
        question = field["question"]
        options = field["options"]
        radio_data = field.get("_radio_data", [])
        matched = self._match_option(answer, options)

        def _click_by_id(rid: str) -> bool:
            """Click label[for=id] first (LinkedIn hides input), fallback to input JS click."""
            try:
                lbl = self.driver.find_element(By.XPATH, f"//label[@for='{rid}']")
                self.driver.execute_script("arguments[0].click();", lbl)
                return True
            except Exception:
                pass
            try:
                el = self.driver.find_element(By.ID, rid)
                self.driver.execute_script("arguments[0].click();", el)
                return True
            except Exception:
                return False

        try:
            # Try to match using JS-collected data (has IDs for precise clicking)
            for r in radio_data:
                label = r.get("label") or r.get("value") or ""
                if matched and _normalize(label) == _normalize(matched):
                    if r.get("id") and _click_by_id(r["id"]):
                        logger.info(f"Selected radio '{label}' for '{question}'")
                        return
            # Fallback: click first option
            if radio_data and radio_data[0].get("id"):
                first = radio_data[0]
                if _click_by_id(first["id"]):
                    logger.warning(f"No radio match for '{answer}' in '{question}' — clicked first: '{first.get('label') or first.get('value')}'")
                    return
            # Last resort: click first element in group
            group = field["el"]
            if group:
                self.driver.execute_script("arguments[0].click();", group[0])
                logger.warning(f"Clicked first radio element for '{question}' as last resort")
        except Exception as e:
            logger.warning(f"Failed to select radio for '{question}': {e}")

    def _apply_checkbox(self, field: dict, answer: str) -> None:
        """Check the checkbox if the answer indicates yes/true."""
        question = field["question"]
        el = field["el"]
        should_check = answer.strip().lower() in ("yes", "sim", "true", "1", "concordo", "aceito")
        try:
            if should_check and not el.is_selected():
                self.driver.execute_script("arguments[0].click();", el)
                logger.info(f"Checked checkbox '{question}'")
            elif not should_check:
                logger.info(f"Left unchecked '{question}' (answer='{answer}')")
        except Exception as e:
            logger.warning(f"Failed to handle checkbox '{question}': {e}")

    def _apply_select(self, field: dict, answer: str) -> None:
        """Apply an answer to a select field with smart retry on validation error."""
        question = field["question"]

        el = None
        try:
            for sel in self.driver.find_elements(By.XPATH, "//select"):
                if sel.is_displayed() and self._get_field_label(sel) == question:
                    el = sel
                    break
        except Exception:
            pass
        el = el or field["el"]

        try:
            opt_elements = Select(el).options
            answer_n = _normalize(answer)
            option_map: dict = field.get("_option_map", {})

            # Build ordered candidate list: best match first, rest appended
            seen_vals: set = set()
            candidates: list[tuple[str, str]] = []  # (value, label)

            def _add(val: str, label: str):
                if val and val not in seen_vals:
                    seen_vals.add(val)
                    candidates.append((val, label))

            # 0. Exact label match
            for label, val in option_map.items():
                if _normalize(label) == answer_n:
                    _add(val, label)

            # 1. Substring on label
            for label, val in option_map.items():
                lbl_n = _normalize(label)
                if answer_n in lbl_n or lbl_n in answer_n:
                    _add(val, label)

            # 2. Word-overlap on label
            answer_words = set(answer_n.split())
            for label, val in option_map.items():
                if answer_words & set(_normalize(label).split()):
                    _add(val, label)

            # 3. Direct value match from DOM
            for opt_el in opt_elements:
                val = opt_el.get_attribute("value")
                if val and _normalize(val) == answer_n:
                    _add(val, opt_el.text.strip())

            # 4. All remaining non-placeholder options as fallback pool
            for opt_el in opt_elements:
                val = opt_el.get_attribute("value")
                if val:
                    _add(val, opt_el.text.strip())

            if not candidates:
                logger.warning(f"No options available for '{question}'")
                return

            # Try candidates in order, stop at first with no validation error
            for val, label in candidates:
                try:
                    el.click()
                    time.sleep(0.3)
                    opt_el = next(
                        (o for o in Select(el).options if o.get_attribute("value") == val),
                        None,
                    )
                    if opt_el:
                        opt_el.click()
                    else:
                        Select(el).select_by_value(val)
                except Exception:
                    try:
                        Select(el).select_by_value(val)
                    except Exception:
                        self.driver.execute_script(_REACT_SET_VALUE, el, val)
                time.sleep(0.3)
                error = self._get_field_error(el)
                if not error:
                    logger.info(f"Selected '{label}' for '{question}'")
                    return
                logger.debug(f"Option '{label}' rejected by validation: {error} — trying next")

            logger.warning(f"All options failed validation for '{question}' — leaving last selected")
        except Exception as e:
            logger.warning(f"Failed to select for '{question}': {e}")

    async def _batch_answer(self, fields: list[dict]) -> dict:
        """Send all form questions to AI in one call. Returns {index: answer}."""
        questions_str = ""
        for i, f in enumerate(fields):
            error_hint = f"   ⚠ ERRO DE VALIDAÇÃO: {f['error']}\n" if f.get("error") else ""
            bad_val_hint = f"   ⚠ VALOR INVÁLIDO ANTERIOR: {f['current_value']}\n" if f.get("current_value") and f.get("error") else ""
            if f["type"] == "textarea":
                questions_str += f"{i}. [TIPO: TEXTO_LONGO] {f['question']}\n{error_hint}{bad_val_hint}"
            elif f["type"] == "text":
                questions_str += f"{i}. [TIPO: TEXTO] {f['question']}\n{error_hint}{bad_val_hint}"
            elif f["type"] == "checkbox":
                questions_str += f"{i}. [TIPO: CHECKBOX] {f['question']}\n   Responda exatamente: Sim ou Não\n{error_hint}"
            else:
                opts_str = "\n   ".join(f["options"])
                questions_str += (
                    f"{i}. [TIPO: SELEÇÃO_ÚNICA] {f['question']}\n"
                    f"   Opções disponíveis (responda com o texto EXATO de uma delas):\n"
                    f"   {opts_str}\n"
                    f"{error_hint}"
                )

        job_context = ""
        if self.job_title:
            job_context = f"\nVAGA: {self.job_title}\n"
        if self.job_description:
            job_context += f"DESCRIÇÃO DA VAGA:\n{self.job_description}\n"

        prompt = f"""Com base no currículo do candidato e na vaga, responda as perguntas do formulário de candidatura abaixo.

CURRÍCULO:
{self.resume}
{job_context}
PERGUNTAS:
{questions_str}
REGRAS OBRIGATÓRIAS:
- Responda APENAS com um objeto JSON, sem texto antes ou depois. Exemplo: {{"0": "3", "1": "Sim", "2": null}}
- [TIPO: TEXTO] campo de texto livre: responda com valor curto em português
- [TIPO: TEXTO_LONGO] campo de texto longo: responda com frase ou parágrafo em português
- [TIPO: TEXTO] campo numérico (anos, salário, etc.): responda SOMENTE com dígitos. Ex: 3 ou 6000
- [TIPO: SELEÇÃO_ÚNICA] OBRIGATÓRIO: responda com o texto EXATO de uma das opções listadas. Não invente opções.
- [TIPO: CHECKBOX] responda exatamente: Sim ou Não
- Use o contexto da vaga para perguntas como "por que se candidatou" ou "experiência com X"
- Se não souber a resposta mesmo com o contexto, coloque null (não coloque "Nulo", "nenhum" ou texto — use null)"""

        result = await get_llm_provider().complete(prompt)
        logger.info(f"AI raw response: {result!r}")

        try:
            import re
            match = re.search(r"\{.*\}", result, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                logger.info(f"AI parsed answers: {parsed}")
                return parsed
        except Exception as e:
            logger.warning(f"Failed to parse AI response as JSON: {e} | raw: {result!r}")
        return {}

    def _match_option(self, answer: str, options: list[str]) -> str | None:
        """Find the best matching option for a given answer string."""
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
