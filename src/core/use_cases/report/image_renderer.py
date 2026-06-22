"""Renderiza report dict como imagem PNG via Playwright (Chromium headless standalone).

Não usa create_context/browser lock — abre Chromium limpo, sem perfil LinkedIn.
"""

from __future__ import annotations

from pathlib import Path


def _fmt_s(s: int) -> str:
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}min"
    return f"{s // 3600}h{(s % 3600) // 60}min"


def _bar(pct: int, color: str = "#4ade80") -> str:
    w = max(0, min(100, pct))
    return (
        f'<div style="background:#2d2d2d;border-radius:4px;height:10px;width:100%">'
        f'<div style="background:{color};width:{w}%;height:10px;border-radius:4px"></div>'
        f"</div>"
    )


def _tile(label: str, value: str, sub: str = "", color: str = "#4ade80") -> str:
    return (
        f'<div style="background:#1e1e2e;border-radius:10px;padding:16px 20px;'
        f'min-width:130px;flex:1">'
        f'<div style="color:#888;font-size:11px;text-transform:uppercase;letter-spacing:.5px">{label}</div>'
        f'<div style="color:{color};font-size:28px;font-weight:700;margin:4px 0">{value}</div>'
        f'<div style="color:#555;font-size:11px">{sub}</div>'
        f"</div>"
    )


def _build_html(report: dict) -> str:
    apps = report.get("applications", 0)
    conns = report.get("connections", 0)
    rejs = report.get("rejections", 0)
    match_pct = report.get("match_rate_pct", 0)
    week = report.get("week", "")
    week_range = report.get("range", "")

    ap = report.get("autopost") or {}
    fu = report.get("followup") or {}
    eng = report.get("engagement") or {}
    ssi = (report.get("ssi") or {}).get("current") or {}
    goals = report.get("goals") or {}
    failures = report.get("failures") or {}
    funnels = report.get("funnels") or {}
    latency = report.get("latency") or {}

    # KPI tiles row
    tiles_html = "".join(
        [
            _tile("Candidaturas", str(apps), f"Conexões: {conns}"),
            _tile("Rejeições", str(rejs), f"Match: {match_pct}%", "#f87171"),
            _tile(
                "Posts",
                str(ap.get("published", 0)),
                f"Gerados: {ap.get('generated', 0)}",
                "#a78bfa",
            ),
            _tile(
                "DMs",
                str(fu.get("sent", 0)),
                f"Gerados: {fu.get('generated', 0)}",
                "#38bdf8",
            ),
            _tile(
                "Engage",
                f"❤️{eng.get('likes', 0)} 💬{eng.get('comments', 0)}",
                "likes + comments",
                "#fb923c",
            ),
        ]
    )

    # SSI block
    ssi_html = ""
    if ssi:
        total = ssi.get("total", 0)
        ssi_html = (
            f'<div style="margin:18px 0 8px">'
            f'<span style="color:#888;font-size:12px">SSI</span> '
            f'<span style="color:#facc15;font-size:18px;font-weight:700">{total}/100</span>'
            f"</div>"
            f"{_bar(total, '#facc15')}"
        )

    # Goals block
    goals_rows = goals.get("rows") or []
    goals_html = ""
    if goals_rows:
        labels = {
            "applications": "Candidaturas",
            "connections": "Conexões",
            "posts": "Posts",
            "comments": "Comments",
        }
        rows_html = "".join(
            f'<div style="margin-bottom:8px">'
            f'<div style="display:flex;justify-content:space-between;color:#ccc;font-size:12px;margin-bottom:3px">'
            f"<span>{'✅' if r['ok'] else '🔸'} {labels.get(r['key'], r['key'])}</span>"
            f"<span>{r['actual']}/{r['target']} ({r['pct']}%)</span>"
            f"</div>"
            f"{_bar(r['pct'], '#4ade80' if r['ok'] else '#fb923c')}"
            f"</div>"
            for r in goals_rows
        )
        goals_html = (
            f'<div style="background:#1e1e2e;border-radius:10px;padding:16px 20px;margin-bottom:14px">'
            f'<div style="color:#888;font-size:11px;text-transform:uppercase;margin-bottom:10px">Metas</div>'
            f"{rows_html}"
            f"</div>"
        )

    # Funnels block
    funnel_labels = {
        "generated": "Ger",
        "approved": "Apr",
        "posted": "Pub",
        "publish_fail": "Fail",
        "offered": "Ofer",
        "sent": "Env",
        "submitted": "Env",
    }
    funnels_html = ""
    if funnels:
        rows_f = []
        for feature, counts in funnels.items():
            steps = list(counts.keys())
            parts = " → ".join(
                f"{funnel_labels.get(s, s)}: {counts[s]}" for s in steps if s in counts
            )
            rows_f.append(
                f'<div style="color:#ccc;font-size:12px;margin-bottom:4px">'
                f'<span style="color:#a78bfa">{feature}</span>  {parts}</div>'
            )
        funnels_html = (
            f'<div style="background:#1e1e2e;border-radius:10px;padding:16px 20px;margin-bottom:14px">'
            f'<div style="color:#888;font-size:11px;text-transform:uppercase;margin-bottom:10px">Funis</div>'
            f"{''.join(rows_f)}"
            f"</div>"
        )

    # Failures + latency
    extra_html = ""
    if failures:
        fail_rows = "".join(
            f'<span style="color:#f87171;font-size:12px">{feat}: {n}x</span>  '
            for feat, n in sorted(failures.items(), key=lambda x: -x[1])
        )
        extra_html += (
            f'<div style="background:#1e1e2e;border-radius:10px;padding:12px 20px;margin-bottom:14px">'
            f'<div style="color:#888;font-size:11px;text-transform:uppercase;margin-bottom:8px">Falhas</div>'
            f"{fail_rows}"
            f"</div>"
        )
    if latency:
        lat_rows = ""
        for feature, metrics in latency.items():
            for lbl, avg_s in metrics.items():
                step = lbl.replace("_avg_s", "").replace("_to_", "→")
                lat_rows += f'<span style="color:#38bdf8;font-size:12px">{feature} {step}: {_fmt_s(avg_s)}</span>  '
        if lat_rows:
            extra_html += (
                f'<div style="background:#1e1e2e;border-radius:10px;padding:12px 20px;margin-bottom:14px">'
                f'<div style="color:#888;font-size:11px;text-transform:uppercase;margin-bottom:8px">Latência</div>'
                f"{lat_rows}"
                f"</div>"
            )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #13131f; color: #e0e0e0; font-family: 'Segoe UI', Arial, sans-serif; padding: 24px; }}
  h1 {{ font-size: 18px; font-weight: 700; color: #fff; }}
  .sub {{ color: #666; font-size: 12px; margin-bottom: 20px; }}
  .tiles {{ display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 18px; }}
  .cols {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }}
</style>
</head>
<body>
  <h1>Relatório Semanal — {week}</h1>
  <div class="sub">{week_range}</div>
  <div class="tiles">{tiles_html}</div>
  <div class="cols">
    <div>
      {goals_html}
      {funnels_html}
    </div>
    <div>
      <div style="background:#1e1e2e;border-radius:10px;padding:16px 20px;margin-bottom:14px">
        <div style="color:#888;font-size:11px;text-transform:uppercase;margin-bottom:10px">SSI</div>
        {ssi_html or '<span style="color:#555">Sem captura</span>'}
      </div>
      {extra_html}
    </div>
  </div>
</body>
</html>"""


def _ensure_chromium() -> None:
    """Instala Chromium headless do Playwright se ainda não estiver disponível."""
    import subprocess
    import sys

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        exec_path = pw.chromium.executable_path
    if Path(exec_path).exists():
        return
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
    )


async def render_report_png(report: dict, out_path: Path) -> None:
    """Render report dict to PNG. Uses standalone Chromium, no LinkedIn session."""
    from playwright.async_api import async_playwright

    _ensure_chromium()
    html = _build_html(report)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 860, "height": 600})
        await page.set_content(html, wait_until="domcontentloaded")
        await page.wait_for_timeout(300)
        await page.screenshot(path=str(out_path), full_page=True)
        await browser.close()
