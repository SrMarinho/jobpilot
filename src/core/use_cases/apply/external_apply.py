"""Candidatura em formulário externo (Gupy, Kenoby, Greenhouse, site próprio).

O que o Easy Apply faz campo a campo, aqui é feito em lote: a página inteira
vira uma lista de campos (:mod:`form_extractor`), o que já está no banco de Q&A
é resolvido sem LLM, e o que sobra vai numa única chamada ao provider.

Reusa ``FormAnswerer`` (cache + config pessoal) e ``FieldFiller`` (escrita e
coerção numérica) sem alterá-los — as duas peças já são independentes do DOM do
LinkedIn. O que **não** é reusado é o ``ModalDriver``, preso ao
``artdeco-modal``, e o ``IndeedApplicationHandler``, que grava a primeira opção
de cada select no cache como se fosse resposta.
"""

from src.config.settings import logger
from src.core.ai.llm_provider import LLMProvider
from src.core.use_cases.apply.field_filler import FieldFiller, is_placeholder
from src.core.use_cases.apply.form_answerer import FormAnswerer, looks_like_refusal
from src.core.use_cases.apply.form_extractor import (
    build_answer_prompt,
    extract_form,
    match_option,
    parse_answer_lines,
    ref_selector,
)

MAX_STEPS = 8
STUCK_LIMIT = 2
STEP_SETTLE_MS = 2500

# Ordem importa: "enviar candidatura" tem que ganhar de "enviar" genérico, e
# nenhum deles pode casar "cancelar"/"voltar".
_ADVANCE_PATTERNS = (
    "enviar candidatura",
    "finalizar candidatura",
    "candidatar-se",
    "candidatar",
    "submit application",
    "finalizar",
    "submit",
    "continuar",
    "próximo",
    "proximo",
    "avançar",
    "avancar",
    "next",
    "continue",
    "enviar",
)

_ADVANCE_JS = """
(patterns) => {
    const norm = (s) => (s || '')
        .normalize('NFKD').replace(/[\\u0300-\\u036f]/g, '')
        .toLowerCase().replace(/\\s+/g, ' ').trim();
    const nodes = Array.from(document.querySelectorAll(
        "button, input[type='submit'], a[role='button'], [role='button']"
    )).filter(el => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return false;
        if (el.disabled) return false;
        const t = norm(el.innerText || el.value || el.getAttribute('aria-label'));
        return t && t.length <= 40;
    });
    // Percorre os padroes em ordem de prioridade, nao os elementos: o botao
    // final do formulario costuma vir depois de um "continuar" escondido.
    for (const p of patterns) {
        for (const el of nodes) {
            const t = norm(el.innerText || el.value || el.getAttribute('aria-label'));
            if (t.includes(p)) return el;
        }
    }
    return null;
}
"""

_SIGNATURE_JS = """
() => (document.body.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 400)
"""


def known_answers_map(cache_data: dict) -> dict[str, str]:
    """``{pergunta original: resposta}`` a partir do documento do cache.

    O cache guarda a chave normalizada; o prompt precisa do enunciado legível,
    que só existe no campo ``original`` das entradas em formato rico. Entradas
    legadas (string pura) usam a própria chave.
    """
    out: dict[str, str] = {}
    for key, entry in (cache_data or {}).items():
        if isinstance(entry, dict):
            question = entry.get("original") or key
            answer = entry.get("answer") or ""
        else:
            question, answer = key, str(entry or "")
        if answer:
            out[str(question)] = str(answer)
    return out


def needs_answer(field: dict) -> bool:
    """Campo ainda sem valor útil.

    Select em "Selecione uma opção" tem ``value`` não-vazio e mesmo assim está
    em branco — é o mesmo engano que fazia o Easy Apply pular campos
    obrigatórios e nunca sair da etapa de revisão.
    """
    if field.get("tag") == "select":
        return is_placeholder(field.get("value"))
    if field.get("type") == "checkbox":
        return field.get("required", False) and not field.get("value")
    return not (field.get("value") or "").strip()


class ExternalApplyHandler:
    def __init__(
        self,
        page,
        *,
        resume_text: str = "",
        resume_file: str | None = None,
        job_title: str = "",
        job_description: str = "",
        answerer: FormAnswerer | None = None,
        provider: LLMProvider | None = None,
        no_submit: bool = False,
    ):
        self.page = page
        self.resume_text = resume_text
        self.resume_file = resume_file
        self.job_title = job_title
        self.job_description = job_description
        self.answerer = answerer or FormAnswerer(provider=provider)
        self.fields = FieldFiller(page)
        self.no_submit = no_submit

    # ── Recon ────────────────────────────────────────────────────────────────

    async def inspect(self) -> list[dict]:
        """Só lê o formulário. Não preenche, não envia, não chama o LLM."""
        return await extract_form(self.page)

    # ── Execução ─────────────────────────────────────────────────────────────

    async def run(self) -> bool:
        signatures: list[str] = []
        for step in range(1, MAX_STEPS + 1):
            fields = await extract_form(self.page)
            pending = [f for f in fields if needs_answer(f)]
            if pending:
                answers = await self._answer_all(pending)
                await self._fill_all(pending, answers)
            await self._upload_resume()

            if self.no_submit:
                logger.info(f"--no-submit: parando na etapa {step} sem enviar")
                return False

            signature = await self._signature()
            if signatures.count(signature) >= STUCK_LIMIT:
                logger.warning(
                    f"Formulário travado na mesma etapa {STUCK_LIMIT}x — parando"
                )
                return False
            signatures.append(signature)

            if not await self._advance(step):
                return False
            await self.page.wait_for_timeout(STEP_SETTLE_MS)

            if await self._looks_done():
                logger.info(f"Candidatura enviada (etapa {step})")
                return True

        logger.warning(f"Formulário não terminou em {MAX_STEPS} etapas")
        return False

    # ── Respostas ────────────────────────────────────────────────────────────

    async def _answer_all(self, pending: list[dict]) -> dict[str, str]:
        """``{ref: resposta}`` para os campos pendentes.

        Cache e config resolvem primeiro, de graça; só o resto vai ao LLM, e vai
        numa chamada só.
        """
        answers: dict[str, str] = {}
        unresolved: list[dict] = []
        for field in pending:
            label = field.get("label") or ""
            cached = self.answerer.resolve(label) if label else None
            if cached:
                answers[field["ref"]] = cached
            else:
                unresolved.append(field)

        if not unresolved:
            logger.info(f"{len(answers)} campo(s) resolvido(s) pelo cache, 0 no LLM")
            return answers

        cache_data = self.answerer.known()
        prompt = build_answer_prompt(
            unresolved,
            job_title=self.job_title,
            job_description=self.job_description,
            resume=self.resume_text,
            known_answers=known_answers_map(cache_data),
        )
        logger.info(
            f"{len(answers)} campo(s) do cache, {len(unresolved)} para o LLM "
            "(1 chamada)"
        )
        model = await self.answerer.provider()
        try:
            raw = await model.complete(prompt)
        except Exception as e:
            logger.error(f"LLM falhou ao responder o formulário: {e}")
            return answers

        fresh = parse_answer_lines(raw, {f["ref"] for f in unresolved})
        by_ref = {f["ref"]: f for f in unresolved}
        for ref, value in fresh.items():
            if not value:
                continue
            if looks_like_refusal(value):
                # Recusa gravada vira texto digitado em todo formulário
                # seguinte — foi o que travou o Easy Apply no campo de celular.
                logger.warning(
                    f"LLM recusou {ref} ({by_ref[ref].get('label', '')[:40]!r}): "
                    f"{value[:60]!r}"
                )
                continue
            answers[ref] = value
            label = by_ref[ref].get("label") or ""
            if label:
                self.answerer.store(
                    label, value, options=by_ref[ref].get("options") or None
                )
        return answers

    # ── Escrita ──────────────────────────────────────────────────────────────

    async def _fill_all(self, pending: list[dict], answers: dict[str, str]) -> None:
        for field in pending:
            value = answers.get(field["ref"], "")
            if not value:
                if field.get("required"):
                    logger.warning(
                        f"Campo obrigatório sem resposta: "
                        f"{field.get('label', '')[:60]!r}"
                    )
                continue
            try:
                await self._fill_one(field, value)
            except Exception as e:
                logger.warning(
                    f"Falha ao preencher {field.get('label', '')[:40]!r}: {e}"
                )

    async def _fill_one(self, field: dict, value: str) -> None:
        tag = field.get("tag")
        label = field.get("label") or ""
        if tag == "radio":
            option = match_option(value, field.get("options") or [])
            if option is None:
                logger.warning(
                    f"Resposta {value!r} não bate com nenhum radio de {label[:40]!r}"
                )
                return
            await self.page.locator(ref_selector(field["ref"], option)).first.check()
            logger.info(f"Radio {label[:40]!r} = {value!r}")
            return

        locator = self.page.locator(ref_selector(field["ref"])).first
        if field.get("type") == "checkbox":
            await locator.check()
            logger.info(f"Checkbox marcado: {label[:40]!r}")
            return
        if tag == "select":
            option = match_option(value, field.get("options") or [])
            if option is None:
                logger.warning(
                    f"Resposta {value!r} não bate com nenhuma opção de {label[:40]!r}"
                )
                return
            await locator.select_option(value=option)
            logger.info(f"Select {label[:40]!r} = {value!r}")
            return

        element = await locator.element_handle()
        if element is None:
            logger.warning(f"Campo {field['ref']} sumiu antes do preenchimento")
            return
        # fill() do FieldFiller faz a coerção numérica ("3 anos" -> "3"), que é
        # o que os ATS validam e rejeitam.
        await self.fields.fill(element, value, question=label)
        logger.info(f"Campo {label[:40]!r} = {value[:40]!r}")

    async def _upload_resume(self) -> None:
        if not self.resume_file:
            return
        try:
            inputs = self.page.locator("input[type='file']")
            count = await inputs.count()
        except Exception:
            return
        for i in range(count):
            field = inputs.nth(i)
            try:
                if await field.input_value():
                    continue
            except Exception:
                pass
            try:
                await field.set_input_files(self.resume_file)
                logger.info(f"Currículo anexado: {self.resume_file}")
            except Exception as e:
                logger.warning(f"Upload do currículo falhou: {e}")

    # ── Navegação ────────────────────────────────────────────────────────────

    async def _signature(self) -> str:
        try:
            return await self.page.evaluate(_SIGNATURE_JS)
        except Exception:
            return ""

    async def _advance(self, step: int) -> bool:
        try:
            handle = await self.page.evaluate_handle(
                _ADVANCE_JS, list(_ADVANCE_PATTERNS)
            )
        except Exception as e:
            logger.warning(f"Busca do botão de avançar falhou: {e}")
            return False
        element = handle.as_element()
        if element is None:
            logger.warning(f"Nenhum botão de avançar/enviar na etapa {step}")
            return False
        try:
            text = (await element.inner_text() or "").strip()
        except Exception:
            text = "?"
        try:
            await element.click(timeout=5000)
        except Exception as e:
            logger.warning(f"Clique em {text!r} falhou: {e}")
            return False
        logger.info(f"Clicou {text!r} (etapa {step})")
        return True

    async def _looks_done(self) -> bool:
        try:
            text = await self.page.evaluate(
                "() => (document.body.innerText || '').toLowerCase()"
            )
        except Exception:
            return False
        markers = (
            "candidatura enviada",
            "candidatura realizada",
            "inscrição realizada",
            "inscricao realizada",
            "application submitted",
            "application received",
            "obrigado por se candidatar",
            "thank you for applying",
        )
        return any(m in text for m in markers)
