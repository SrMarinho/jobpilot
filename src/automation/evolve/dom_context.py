"""Descreve o DOM pro LLM sem mandar HTML.

Uma página do LinkedIn passa de 1 MB de HTML. Mandar isso é impossível e
também inútil: o que o modelo precisa pra propor um seletor é a lista de
elementos candidatos com seus atributos estáveis, não a árvore inteira.

Mesma tática do ``form_extractor``: um único ``evaluate`` devolve uma lista de
descritores. A diferença é o critério de coleta — aqui o alvo é "elemento que
alguém poderia querer selecionar", então o filtro é por tag/role de interesse,
visibilidade e área, com corte duro na quantidade.

O escopo importa mais que o filtro. Quando o campo é de dentro de um modal, a
raiz da coleta é o próprio modal; e **não encontrar modal nenhum é a
informação mais valiosa que essa função pode devolver** — foi exatamente o que
aconteceu com o ``invite modal`` (o LinkedIn parou de abrir o modal, e 711
warnings depois ninguém sabia disso). Por isso a ausência é dita em texto, em
vez de virar uma lista vazia silenciosa.

Tudo roda sobre um ``Locator``, nunca sobre ``Page``: as duas APIs de
``evaluate`` têm assinatura diferente (no locator o elemento chega como
primeiro argumento) e compartilhar um único JS entre as duas daria erro em
runtime. Página inteira entra como ``page.locator("body")``.
"""

from __future__ import annotations

from playwright.async_api import Locator, Page

from src.config.settings import logger

# Orçamento de contexto. 40 elementos cobrem com folga um modal ou a região
# útil de uma página; o corte de caracteres é a rede de segurança para
# atributos gigantes (o LinkedIn tem aria-label de 200 chars).
MAX_ELEMENTS = 40
MAX_CHARS = 7_000

_DIALOG_ROOTS = (
    "[data-test-modal-container]",
    "[role='dialog']",
    "[role='alertdialog']",
    "dialog[open]",
    ".artdeco-modal",
)

# Recebe (elemento_raiz, {maxElements}) — forma do `locator.evaluate`.
_DESCRIBE_JS = """
(root, arg) => {
    const maxElements = arg.maxElements;
    const sel = [
        'button', 'a[href]', 'input', 'textarea', 'select',
        '[role]', '[aria-label]', '[data-test]', '[data-testid]',
        'h1', 'h2', 'h3'
    ].join(',');

    const visible = (el) => {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) return false;
        const s = window.getComputedStyle(el);
        if (s.visibility === 'hidden' || s.display === 'none') return false;
        return parseFloat(s.opacity || '1') > 0.05;
    };

    const dataAttrs = (el) => {
        const out = {};
        for (const attr of el.attributes) {
            // Só os data-* que costumam ser estáveis entre deploys. Valor
            // longo é tracking (urn, id numérico) e muda por item.
            if (!attr.name.startsWith('data-')) continue;
            if (attr.value && attr.value.length > 60) continue;
            out[attr.name] = attr.value;
        }
        return out;
    };

    const nodes = Array.from(root.querySelectorAll(sel)).filter(visible);

    // Ordena por profundidade (mais raso primeiro) e depois por posição: um
    // seletor de container é mais útil que um de folha, e o topo da tela é
    // onde estão os elementos que interessam.
    const scored = nodes.map((el) => {
        let depth = 0;
        for (let p = el.parentElement; p; p = p.parentElement) depth++;
        const r = el.getBoundingClientRect();
        return { el: el, depth: depth, top: Math.round(r.top), rect: r };
    });
    scored.sort((a, b) => (a.depth - b.depth) || (a.top - b.top));

    const described = scored.slice(0, maxElements).map((item) => ({
        tag: item.el.tagName.toLowerCase(),
        id: item.el.id || null,
        role: item.el.getAttribute('role'),
        ariaLabel: (item.el.getAttribute('aria-label') || '').slice(0, 80) || null,
        text: (item.el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 60) || null,
        classes: Array.from(item.el.classList).slice(0, 4),
        data: dataAttrs(item.el),
        w: Math.round(item.rect.width),
        h: Math.round(item.rect.height),
        disabled: item.el.disabled === true
            || item.el.getAttribute('aria-disabled') === 'true'
    }));

    return {
        title: document.title,
        path: location.pathname,
        head: (document.body.innerText || '')
            .replace(/\\s+/g, ' ').trim().slice(0, 300),
        total: nodes.length,
        elements: described
    };
}
"""


async def _dialog_root(page: Page) -> tuple[Locator | None, str]:
    """Primeiro container de modal visível, e o seletor que o achou."""
    for candidate in _DIALOG_ROOTS:
        try:
            locator = page.locator(candidate).first
            if await locator.is_visible(timeout=500):
                return locator, candidate
        except Exception:
            continue
    return None, ""


def _as_locator(root: Page | Locator) -> Locator:
    """``Page`` vira o ``body``; ``Locator`` passa direto."""
    if isinstance(root, Page):
        return root.locator("body").first
    return root


async def capture(
    root: Page | Locator, *, scope: str = "page", max_elements: int = MAX_ELEMENTS
) -> str:
    """Descrição textual do DOM relevante, pronta pro prompt.

    ``root`` é o que o resolver estava usando quando falhou (página ou card).
    Para ``scope="dialog"`` procura o modal aberto e, se não achar, diz isso em
    voz alta e descreve a página — a ausência do modal costuma ser a resposta.
    """
    alvo = root
    aviso = ""

    if scope == "dialog" and isinstance(root, Page):
        dialog, achado = await _dialog_root(root)
        if dialog is None:
            aviso = (
                "ATENÇÃO: nenhum container de modal/diálogo visível na página. "
                "O elemento procurado pode simplesmente não existir neste "
                "momento (o site pode ter deixado de abrir esse modal).\n\n"
            )
        else:
            alvo = dialog
            aviso = f"(modal encontrado por: {achado})\n\n"

    try:
        data = await _as_locator(alvo).evaluate(
            _DESCRIBE_JS, {"maxElements": max_elements}
        )
    except Exception as e:
        logger.warning(f"[evolve] captura de DOM falhou: {e}")
        return f"{aviso}(não foi possível descrever o DOM: {type(e).__name__})"

    return aviso + render(data)


def render(data: dict) -> str:
    """Formata os descritores em texto compacto e determinístico.

    Puro para poder ser testado sem browser: o formato é o que o modelo lê, e
    mudança aqui muda a qualidade da cura.
    """
    linhas = [
        f"Página: {data.get('title', '?')} ({data.get('path', '?')})",
        f"Elementos visíveis de interesse: {data.get('total', 0)} "
        f"(mostrando {len(data.get('elements', []))})",
        "",
    ]
    for index, el in enumerate(data.get("elements", []), start=1):
        partes = [f"{index}. <{el.get('tag')}>"]
        if el.get("id"):
            partes.append(f"id={el['id']!r}")
        if el.get("role"):
            partes.append(f"role={el['role']!r}")
        if el.get("ariaLabel"):
            partes.append(f"aria-label={el['ariaLabel']!r}")
        for nome, valor in (el.get("data") or {}).items():
            partes.append(f"{nome}={valor!r}" if valor else nome)
        if el.get("classes"):
            partes.append("class=" + ".".join(el["classes"]))
        if el.get("text"):
            partes.append(f"texto={el['text']!r}")
        partes.append(f"{el.get('w', 0)}x{el.get('h', 0)}")
        if el.get("disabled"):
            partes.append("DESABILITADO")
        linhas.append("  ".join(partes))

    head = data.get("head")
    if head:
        linhas += ["", f"Texto inicial da página: {head!r}"]

    texto = "\n".join(linhas)
    if len(texto) > MAX_CHARS:
        # Corte determinístico: o prompt tem orçamento, e truncar no meio de um
        # descritor é melhor que estourar e falhar a chamada.
        texto = texto[:MAX_CHARS] + "\n(descrição truncada)"
    return texto
