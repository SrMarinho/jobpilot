"""Lê um formulário de candidatura inteiro de uma vez e monta o prompt do LLM.

O Easy Apply resolve campo a campo: descobre o rótulo, pergunta ao LLM, escreve,
repete. Funciona porque o modal do LinkedIn mostra dois ou três campos por etapa.
Num ATS externo (Gupy, Kenoby, Greenhouse) a mesma estratégia custaria uma
chamada de LLM por campo em formulários de vinte campos, e cada pergunta
chegaria ao modelo sem as outras por contexto.

Aqui a página vira uma lista de descritores num único ``page.evaluate``, e as
perguntas ainda sem resposta viram **uma** chamada ao provider. A interface do
provider é ``complete(prompt: str) -> str`` — sem imagem e sem JSON schema — então
o formato de ida e volta é texto delimitado por ``|``, o mesmo padrão que o
``job_evaluator`` usa para avaliar vagas em lote.
"""

import re

from src.config.settings import logger

# Marca cada campo com um id sintético. Um selector CSS montado na hora
# (nth-child, classe gerada) quebra assim que o ATS re-renderiza; o atributo
# viaja com o elemento.
REF_ATTR = "data-jp-ref"

_EXTRACT_JS = """
(refAttr) => {
    const visible = (el) => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return false;
        const s = window.getComputedStyle(el);
        return s.visibility !== 'hidden' && s.display !== 'none';
    };

    // Mesma cadeia do FieldFiller.label_of: label[for] -> aria-label ->
    // placeholder -> legend do fieldset -> texto do pai.
    const labelOf = (el) => {
        const id = el.getAttribute('id');
        if (id) {
            const esc = (window.CSS && CSS.escape) ? CSS.escape(id) : id;
            const l = document.querySelector('label[for="' + esc + '"]');
            if (l && l.innerText.trim()) return l.innerText.trim();
        }
        const wrapping = el.closest('label');
        if (wrapping && wrapping.innerText.trim()) return wrapping.innerText.trim();
        const aria = el.getAttribute('aria-label');
        if (aria && aria.trim()) return aria.trim();
        const labelledby = el.getAttribute('aria-labelledby');
        if (labelledby) {
            const parts = labelledby.split(/\\s+/)
                .map(x => document.getElementById(x))
                .filter(Boolean)
                .map(x => x.innerText.trim())
                .filter(Boolean);
            if (parts.length) return parts.join(' ');
        }
        const ph = el.getAttribute('placeholder');
        if (ph && ph.trim()) return ph.trim();
        const fs = el.closest('fieldset');
        if (fs) {
            const leg = fs.querySelector('legend');
            if (leg && leg.innerText.trim()) return leg.innerText.trim();
        }
        // Ultimo recurso: texto do ancestral mais proximo que tenha texto
        // proprio curto o bastante para ser um enunciado.
        let cur = el.parentElement;
        for (let i = 0; i < 4 && cur; i++) {
            const t = (cur.innerText || '').trim();
            if (t && t.length <= 200) return t;
            cur = cur.parentElement;
        }
        return '';
    };

    const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim().slice(0, 200);

    const fields = [];
    let n = 0;
    const seenRadioGroups = new Set();

    const controls = document.querySelectorAll('input, select, textarea');
    for (const el of controls) {
        const type = (el.getAttribute('type') || '').toLowerCase();
        const tag = el.tagName.toLowerCase();
        if (tag === 'input' && ['hidden', 'submit', 'button', 'image', 'reset'].includes(type)) {
            continue;
        }
        if (tag === 'input' && type === 'file') continue;  // currículo é tratado à parte
        if (!visible(el)) continue;

        if (tag === 'input' && type === 'radio') {
            const name = el.getAttribute('name') || '';
            if (!name || seenRadioGroups.has(name)) continue;
            seenRadioGroups.add(name);
            const group = Array.from(
                document.querySelectorAll('input[type="radio"][name="' + name + '"]')
            );
            const ref = 'f' + (++n);
            const options = [];
            let checked = '';
            for (const r of group) {
                r.setAttribute(refAttr, ref + ':' + r.value);
                const lbl = clean(labelOf(r)) || r.value;
                options.push([r.value, lbl]);
                if (r.checked) checked = r.value;
            }
            const fs = el.closest('fieldset');
            const leg = fs && fs.querySelector('legend');
            fields.push({
                ref, tag: 'radio', type: 'radio', name,
                required: group.some(r => r.required),
                label: clean(leg ? leg.innerText : labelOf(el)),
                options, value: checked,
            });
            continue;
        }

        const ref = 'f' + (++n);
        el.setAttribute(refAttr, ref);
        let options = [];
        if (tag === 'select') {
            options = Array.from(el.options).map(o => [o.value, clean(o.text)]);
        }
        fields.push({
            ref,
            tag,
            type: type || null,
            name: el.getAttribute('name') || '',
            required: !!el.required || el.getAttribute('aria-required') === 'true',
            label: clean(labelOf(el)),
            options,
            value: tag === 'select' ? (el.value || '') :
                   (type === 'checkbox' ? (el.checked ? 'on' : '') : (el.value || '')),
        });
    }
    return fields;
}
"""


async def extract_form(page) -> list[dict]:
    """Descritores de todos os campos visíveis da página, já marcados com ref.

    Efeito colateral proposital: escreve ``data-jp-ref`` em cada campo, que é
    como o preenchimento reencontra o elemento depois.
    """
    try:
        fields = await page.evaluate(_EXTRACT_JS, REF_ATTR)
    except Exception as e:
        logger.warning(f"Extração do formulário falhou: {e}")
        return []
    logger.info(f"Formulário: {len(fields)} campo(s) visível(is)")
    return fields


def ref_selector(ref: str, value: str | None = None) -> str:
    """Selector do campo (ou da opção de radio) marcado com ``ref``."""
    if value is None:
        return f"[{REF_ATTR}='{ref}']"
    return f"[{REF_ATTR}='{ref}:{value}']"


def describe_field(field: dict) -> str:
    """Uma linha por campo, do jeito que o LLM vai ler."""
    parts = [
        field["ref"],
        field.get("label") or "(sem rótulo)",
        field.get("tag", ""),
    ]
    if field.get("required"):
        parts.append("obrigatório")
    options = field.get("options") or []
    if options:
        # Só o texto visível: o value é detalhe de implementação e confunde o
        # modelo. A conversão texto->value acontece na hora de preencher.
        shown = [text for _value, text in options if text]
        parts.append("opções: " + " / ".join(shown[:25]))
    return " | ".join(p for p in parts if p)


def build_answer_prompt(
    fields: list[dict],
    *,
    job_title: str,
    job_description: str,
    resume: str,
    known_answers: dict[str, str],
) -> str:
    """Prompt único com todos os campos pendentes.

    ``known_answers`` é o banco de Q&A inteiro (pergunta original -> resposta).
    Vai no prompt de propósito: a chave do ``FormAnswerCache`` é match exato
    normalizado, então "Qual seu CPF?" e "Informe seu CPF *" são entradas
    distintas e a segunda nasce vazia. O modelo faz o casamento semântico que o
    cache não faz.
    """
    known = "\n".join(f"- {q} -> {a}" for q, a in known_answers.items() if a)
    lines = "\n".join(describe_field(f) for f in fields)
    return (
        "Você está preenchendo um formulário de candidatura em nome do "
        "candidato abaixo. Responda cada campo na primeira pessoa do candidato.\n\n"
        f"VAGA: {job_title}\n"
        f"DESCRIÇÃO: {job_description[:2000]}\n\n"
        f"CURRÍCULO:\n{resume[:4000]}\n\n"
        f"RESPOSTAS JÁ DADAS EM OUTROS FORMULÁRIOS (use quando a pergunta for "
        f"equivalente, mesmo com outro texto):\n{known or '(nenhuma)'}\n\n"
        f"CAMPOS A PREENCHER (ref | rótulo | tipo | opções):\n{lines}\n\n"
        "REGRAS:\n"
        "- Uma linha por campo, no formato exato: ref|resposta\n"
        "- Quando houver opções, responda com o TEXTO EXATO de uma delas.\n"
        "- Campo numérico: só o número, sem unidade.\n"
        "- Nunca invente formação, certificação ou experiência que não esteja "
        "no currículo nem nas respostas já dadas.\n"
        "- Se não souber e o campo não for obrigatório, responda: ref|\n"
        "- Sem explicação, sem cabeçalho, sem markdown. Só as linhas ref|resposta."
    )


_ANSWER_LINE = re.compile(r"^\s*(f\d+)\s*\|(.*)$")


def parse_answer_lines(raw: str, valid_refs: set[str]) -> dict[str, str]:
    """Converte a saída do LLM em ``{ref: resposta}``.

    Tolerante de propósito: modelos locais gostam de embrulhar a resposta em
    ```` ``` ```` ou de abrir com "Aqui estão as respostas". Linha que não casa
    o formato é descartada em silêncio; ref desconhecido é descartado com aviso,
    porque isso é alucinação e não ruído de formatação.
    """
    answers: dict[str, str] = {}
    for line in (raw or "").splitlines():
        m = _ANSWER_LINE.match(line.strip().strip("`"))
        if not m:
            continue
        ref, value = m.group(1), m.group(2).strip()
        if ref not in valid_refs:
            logger.warning(f"LLM devolveu ref inexistente: {ref!r}")
            continue
        answers[ref] = value
    return answers


def match_option(answer: str, options: list) -> str | None:
    """Converte o texto respondido no ``value`` da opção correspondente.

    Casamento em três níveis — exato, sem acento/caixa, e por continência —
    porque o modelo responde "Sim" onde a opção é "Sim, aceito" e um select
    rejeita um ``value`` que não existe.
    """
    from src.utils.text import normalize

    if not options:
        return None
    target = normalize(answer).strip()
    if not target:
        return None
    pairs = [(str(v), str(t)) for v, t in options]
    for value, text in pairs:
        if text == answer or value == answer:
            return value
    for value, text in pairs:
        if normalize(text).strip() == target or normalize(value).strip() == target:
            return value
    for value, text in pairs:
        norm = normalize(text).strip()
        if norm and (norm in target or target in norm):
            return value
    return None
