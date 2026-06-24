"""Render de card de post: design system + texto -> PNG (HTML + Playwright).

Mesmo padrão do ``report/image_renderer.py`` (Chromium standalone, sem sessão
LinkedIn). Recebe título/subtítulo + um design system (tokens) e devolve um PNG
on-brand, gerado 100% local — sem Canva, sem Enterprise.
"""

from __future__ import annotations

import html as _html
import re
from pathlib import Path

from src.config.settings import logger
from src.core.use_cases.post_image.design_system import load_design_system


def _esc(text: str) -> str:
    return _html.escape((text or "").strip())


# Domínio técnico -> tag do kicker. Ordem importa (1º match vence). NUNCA usa o
# nome do formato (dissertativo/snippet) — isso não diz nada ao leitor.
_DOMAIN_TAGS = (
    (r"code review|pull request|\bpr\b|revis[ãa]o de c[óo]digo", "CODE REVIEW"),
    (r"\bapis?\b|rest|graphql|endpoint", "API"),
    (r"kubernetes|k8s|docker|devops|ci/cd|cicd|deploy|pipeline", "DEVOPS"),
    (r"sql|postgres|mysql|mongo|banco de dados|database|\bdados\b", "DATA"),
    (r"react|vue|angular|frontend|front-end|css", "FRONTEND"),
    (r"arquitetura|architecture|microservi|design pattern", "ARQUITETURA"),
    (r"performance|lat[êe]ncia|throughput|otimiza", "PERFORMANCE"),
    (r"security|seguran[çc]a|\bauth\b|autentica|token", "SEGURANÇA"),
    (r"\btest|\bteste|tdd|mock", "TESTES"),
    (r"\bllm\b|\bia\b|\bai\b|machine learning|intelig[êe]ncia artificial", "IA"),
    (r"python|node|java|golang|rust|backend|back-end", "BACKEND"),
)


def _domain_kicker(text: str) -> str:
    low = (text or "").lower()
    for pat, tag in _DOMAIN_TAGS:
        if re.search(pat, low):
            return f"// {tag}"
    return ""


def derive_card_copy(topic: str, content: str = "", fmt: str = "") -> dict:
    """Deriva título/subtítulo/kicker do card a partir do tópico (heurístico).

    Se o tópico tem separador ("X: Y", "X — Y"), vira título + subtítulo. Senão,
    usa o tópico como título e a 1ª frase do conteúdo como subtítulo. O kicker é o
    DOMÍNIO técnico (// API, // BACKEND…) inferido do texto, ou vazio. Sem LLM.
    """
    topic = (topic or "").strip()
    title, subtitle = topic, ""
    for sep in (": ", " — ", " – ", " - "):
        if sep in topic:
            head, tail = topic.split(sep, 1)
            title, subtitle = head.strip(), tail.strip()
            break
    if not subtitle and content:
        first = re.split(r"(?<=[.!?])\s", content.strip(), maxsplit=1)[0]
        subtitle = first.strip()
    return {
        "title": _cap(title[:48].strip()),
        "subtitle": _cap(subtitle[:96].strip()),
        # só o tópico (não o corpo): tag precisa ou vazia, nunca solta
        "kicker": _domain_kicker(topic)[:40],
    }


def _cap(text: str) -> str:
    """Capitaliza só a 1ª letra (preserva o resto — siglas, camelCase)."""
    return text[:1].upper() + text[1:] if text else text


def build_card_html(ds: dict, title: str, subtitle: str = "", kicker: str = "") -> str:
    """Monta o HTML do card a partir dos tokens do design system."""
    c = ds["colors"]
    f = ds["fonts"]
    canvas = ds["canvas"]
    sig = ds.get("signature", {})
    google = f.get("google_href", "")
    font_link = f'<link rel="stylesheet" href="{google}">' if google else ""

    kicker_html = f'<div class="kicker">{_esc(kicker)}</div>' if kicker else ""
    subtitle_html = f'<div class="subtitle">{_esc(subtitle)}</div>' if subtitle else ""
    sig_name = _esc(sig.get("name", ""))
    sig_role = _esc(sig.get("role", ""))
    sig_html = ""
    if sig_name or sig_role:
        role = f"· {sig_role}" if sig_role else ""
        sig_html = (
            f'<div class="sig"><span class="dot"></span>'
            f'<span class="sig-name">{sig_name}</span>'
            f'<span class="sig-role">{role}</span></div>'
        )

    return f"""<!doctype html>
<html lang="pt-br"><head><meta charset="utf-8">{font_link}
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{
    width: {canvas["width"]}px; height: {canvas["height"]}px;
    overflow: hidden;
  }}
  .card {{
    position: relative; width: {canvas["width"]}px; height: {canvas["height"]}px;
    background:
      radial-gradient(120% 80% at 80% 0%, {c["bg2"]} 0%, {c["bg"]} 60%);
    font-family: {f["title"]}; color: {c["text"]};
    padding: 96px 96px 84px 96px; display: flex; flex-direction: column;
  }}
  /* grid/linhas técnicas (vibe blueprint) */
  .grid {{
    position: absolute; inset: 0;
    background-image:
      linear-gradient({c["grid"]} 1px, transparent 1px),
      linear-gradient(90deg, {c["grid"]} 1px, transparent 1px);
    background-size: 60px 60px;
    mask-image: radial-gradient(130% 90% at 70% 10%, #000 40%, transparent 95%);
  }}
  /* crosshair de coordenadas no canto superior direito */
  .cross {{
    position: absolute; top: 72px; right: 72px; width: 220px; height: 220px;
    opacity: .9;
  }}
  .cross::before, .cross::after {{
    content: ""; position: absolute; background: {c["accent_soft"]};
  }}
  .cross::before {{ top: 0; right: 0; width: 2px; height: 220px; }}
  .cross::after  {{ top: 0; right: 0; width: 220px; height: 2px; }}
  .node {{
    position: absolute; top: -5px; right: -5px; width: 12px; height: 12px;
    border-radius: 50%; background: {c["accent_soft"]};
    box-shadow: 0 0 0 6px rgba(138,154,91,.15);
  }}
  .content {{ margin-top: auto; position: relative; z-index: 2; }}
  .bar {{
    width: 64px; height: 6px; background: {c["accent_soft"]};
    border-radius: 3px; margin-bottom: 32px;
  }}
  .kicker {{
    font-family: {f["mono"]}; font-size: 26px; letter-spacing: .18em;
    text-transform: uppercase; color: {c["accent_soft"]}; margin-bottom: 24px;
  }}
  .title {{
    font-size: 96px; font-weight: 800; line-height: 1.04;
    letter-spacing: -.01em; max-width: 14ch;
  }}
  .subtitle {{
    margin-top: 28px; font-size: 40px; font-weight: 400; line-height: 1.3;
    color: {c["muted"]}; max-width: 24ch;
  }}
  .footer {{
    position: relative; z-index: 2; margin-top: 56px;
    display: flex; align-items: center; justify-content: space-between;
    border-top: 1px solid rgba(147,160,143,.18); padding-top: 28px;
  }}
  .sig {{ display: flex; align-items: center; font-size: 30px; }}
  .dot {{
    width: 14px; height: 14px; background: {c["accent"]};
    border: 2px solid {c["accent_soft"]}; margin-right: 16px;
  }}
  .sig-name {{ font-weight: 600; }}
  .sig-role {{ color: {c["muted"]}; margin-left: 10px; }}
  .tag {{
    font-family: {f["mono"]}; font-size: 26px; color: {c["accent_soft"]};
  }}
</style></head>
<body>
  <div class="card">
    <div class="grid"></div>
    <div class="cross"><span class="node"></span></div>
    <div class="content">
      <div class="bar"></div>
      {kicker_html}
      <div class="title">{_esc(title)}</div>
      {subtitle_html}
    </div>
    <div class="footer">
      {sig_html}
      <div class="tag">&gt;_</div>
    </div>
  </div>
</body></html>"""


async def render_card_png(
    title: str,
    subtitle: str = "",
    out_path: str | Path = "card.png",
    kicker: str = "",
    ds: dict | None = None,
) -> Path:
    """Renderiza o card para PNG no tamanho do canvas. Retorna o caminho."""
    from playwright.async_api import async_playwright

    ds = ds or load_design_system()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = ds["canvas"]
    html = build_card_html(ds, title, subtitle, kicker)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page(
                viewport={"width": canvas["width"], "height": canvas["height"]},
                device_scale_factor=2,
            )
            await page.set_content(html, wait_until="networkidle")
            await page.wait_for_timeout(300)  # margem p/ fontes assentarem
            await page.screenshot(path=str(out_path), full_page=False)
        finally:
            await browser.close()

    logger.info(f"Card PNG renderizado: {out_path} ({title!r})")
    return out_path
