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


def _card(title: str, body: str) -> str:
    return (
        f'<div style="background:#1e1e2e;border-radius:10px;padding:16px 20px;margin-bottom:14px">'
        f'<div style="color:#888;font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px">{title}</div>'
        f"{body}"
        f"</div>"
    )


def _row(label: str, value: str, color: str = "#ccc") -> str:
    return (
        f'<div style="display:flex;justify-content:space-between;'
        f'color:{color};font-size:12px;margin-bottom:4px">'
        f"<span>{label}</span><span>{value}</span></div>"
    )


def _build_html(report: dict) -> str:  # noqa: PLR0912, PLR0914
    apps = report.get("applications", 0)
    conns = report.get("connections", 0)
    rejs = report.get("rejections", 0)
    match_pct = report.get("match_rate_pct", 0)
    week = report.get("week", "")
    week_range = report.get("range", "")

    ap = report.get("autopost") or {}
    fu = report.get("followup") or {}
    eng = report.get("engagement") or {}
    ssi_data = report.get("ssi") or {}
    ssi = ssi_data.get("current") or {}
    goals = report.get("goals") or {}
    failures = report.get("failures") or {}
    funnels = report.get("funnels") or {}
    latency = report.get("latency") or {}
    salary = report.get("avg_salary_offered")
    qa_pending = report.get("qa_pending", 0)
    site_apps = report.get("site_applications") or {}
    site_rejs = report.get("site_rejections") or {}
    level_bd = report.get("level_breakdown") or {}
    rej_bd = report.get("rejection_breakdown") or {}
    skills = report.get("top_skills") or []

    # ── KPI tiles ────────────────────────────────────────────────
    sal_sub = f"R$ {salary:,.0f}".replace(",", ".") if salary else ""
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
                f"Shares: {eng.get('shares', 0)}",
                "#fb923c",
            ),
            _tile(
                "Salário",
                sal_sub or "—",
                f"QA pendente: {qa_pending}" if qa_pending else "",
                "#facc15",
            ),
        ]
    )

    # ── Col A: Metas + Site ───────────────────────────────────────
    goal_labels = {
        "applications": "Candidaturas",
        "connections": "Conexões",
        "posts": "Posts",
        "comments": "Comments",
    }
    goals_rows = goals.get("rows") or []
    goals_body = "".join(
        f'<div style="margin-bottom:8px">'
        f'<div style="display:flex;justify-content:space-between;color:#ccc;font-size:12px;margin-bottom:3px">'
        f"<span>{'✅' if r['ok'] else '🔸'} {goal_labels.get(r['key'], r['key'])}</span>"
        f"<span>{r['actual']}/{r['target']} ({r['pct']}%)</span></div>"
        f"{_bar(r['pct'], '#4ade80' if r['ok'] else '#fb923c')}</div>"
        for r in goals_rows
    )
    behind = goals.get("behind") or []
    if behind:
        goals_body += f'<div style="color:#fb923c;font-size:11px;margin-top:6px">Atrás: {", ".join(goal_labels.get(k, k) for k in behind)}</div>'
    col_a = _card("Metas", goals_body) if goals_rows else ""

    site_body = ""
    for s in ("linkedin", "indeed", "glassdoor"):
        a = site_apps.get(s, 0)
        r = site_rejs.get(s, 0)
        if not a and not r:
            continue
        seen = a + r
        rate = round(a / seen * 100) if seen else 0
        site_body += _row(s.capitalize(), f"{a} aplic / {r} rej ({rate}%)")
    col_a += _card("Por site", site_body or '<span style="color:#555">—</span>')

    rej_body = "".join(
        _row(k, f"{v}x", "#f87171")
        for k, v in sorted(rej_bd.items(), key=lambda x: -x[1])
    )
    col_a += _card("Motivos rejeição", rej_body or '<span style="color:#555">—</span>')

    level_order = ["junior", "pleno", "senior", "unknown"]
    level_body = "".join(
        _row(k, f"{level_bd[k]}x") for k in level_order if level_bd.get(k)
    )
    skills_body = "".join(
        f'<div style="color:#ccc;font-size:12px;margin-bottom:3px">'
        f'{i + 1}. {s["skill"]} <span style="color:#888">({s["count"]}x)</span></div>'
        for i, s in enumerate(skills)
    )
    col_a += _card("Por nível", level_body or '<span style="color:#555">—</span>')
    col_a += _card("Top skills", skills_body or '<span style="color:#555">—</span>')

    # ── Col B: SSI + Autopost + Followup ─────────────────────────
    if ssi:
        total = ssi.get("total", 0)

        def _dstr(key: str) -> str:
            d = ssi_data.get(f"delta_{key}")
            if d is None:
                return ""
            return f' <span style="color:{"#4ade80" if d > 0 else "#f87171"}">{"↑" if d > 0 else "↓"}{abs(d)}</span>'

        ssi_body = (
            f'<div style="margin-bottom:10px">'
            f'<span style="color:#facc15;font-size:22px;font-weight:700">{total}/100</span>{_dstr("total")}'
            f"</div>"
            f"{_bar(total, '#facc15')}"
            f'<div style="margin-top:12px">'
        )
        for comp, label in (
            ("brand", "Marca profissional"),
            ("find_people", "Pessoas certas"),
            ("engage_insights", "Interagir c/ insights"),
            ("relationships", "Relacionamentos"),
        ):
            v = ssi.get(comp, 0)
            pct25 = round(v / 25 * 100)
            ssi_body += (
                f'<div style="margin-bottom:8px">'
                f'<div style="display:flex;justify-content:space-between;color:#ccc;font-size:11px;margin-bottom:3px">'
                f"<span>{label}</span><span>{v}/25{_dstr(comp)}</span></div>"
                f"{_bar(pct25, '#facc15')}</div>"
            )
        rank_parts = []
        if ssi.get("rank_industry_pct") is not None:
            rank_parts.append(f"Top {ssi['rank_industry_pct']}% setor")
        if ssi.get("rank_network_pct") is not None:
            rank_parts.append(f"Top {ssi['rank_network_pct']}% rede")
        if rank_parts:
            ssi_body += f'<div style="color:#888;font-size:11px;margin-top:6px">{" · ".join(rank_parts)}</div>'
        ssi_body += "</div>"
    else:
        ssi_body = '<span style="color:#555">Sem captura esta semana</span>'
    col_b = _card("SSI", ssi_body)

    ap_gen = ap.get("generated", 0)
    ap_aprov = round(ap.get("approved", 0) / ap_gen * 100) if ap_gen else 0
    fmt_parts = "  ".join(
        f"{k}: {v}x"
        for k, v in sorted(ap.get("by_format", {}).items(), key=lambda x: -x[1])
    )
    ap_body = (
        _row("Publicados", str(ap.get("published", 0)), "#a78bfa")
        + _row("Gerados", str(ap_gen))
        + _row("Aprovação", f"{ap_aprov}%")
        + _row("Média chars", str(ap.get("avg_chars", 0)))
        + (
            f'<div style="color:#555;font-size:11px;margin-top:4px">{fmt_parts}</div>'
            if fmt_parts
            else ""
        )
    )
    col_b += _card("Autopost", ap_body)

    fu_body = _row("Enviados", str(fu.get("sent", 0)), "#38bdf8") + _row(
        "Gerados", str(fu.get("generated", 0))
    )
    col_b += _card("Follow-up DM", fu_body)

    # ── Col C: Engagement + Funis + Falhas + Latência ────────────
    top_authors = eng.get("top_authors") or []
    by_variant = eng.get("by_variant") or {}
    eng_body = (
        _row("❤️ Likes", str(eng.get("likes", 0)), "#fb923c")
        + _row("💬 Comments", str(eng.get("comments", 0)), "#fb923c")
        + _row("🔁 Shares", str(eng.get("shares", 0)), "#fb923c")
    )
    if top_authors:
        eng_body += '<div style="color:#888;font-size:11px;margin-top:6px;margin-bottom:3px">Top autores</div>'
        eng_body += "".join(_row(name, f"{n}x") for name, n in top_authors[:4])
    if by_variant:
        eng_body += '<div style="color:#888;font-size:11px;margin-top:6px;margin-bottom:3px">A/B comentário</div>'
        eng_body += "".join(
            _row(k, f"{v}x") for k, v in sorted(by_variant.items(), key=lambda x: -x[1])
        )
    col_c = _card("Engagement", eng_body)

    funnel_labels = {
        "generated": "Ger",
        "approved": "Apr",
        "posted": "Pub",
        "publish_fail": "Fail",
        "offered": "Ofer",
        "sent": "Env",
        "submitted": "Env",
    }
    if funnels:
        fn_body = ""
        for feature, counts in funnels.items():
            parts = " → ".join(
                f"{funnel_labels.get(s, s)}: {counts[s]}"
                for s in counts
                if counts[s] or True
            )
            fn_body += f'<div style="color:#ccc;font-size:12px;margin-bottom:5px"><span style="color:#a78bfa">{feature}</span>  {parts}</div>'
        col_c += _card("Funis", fn_body)

    if failures:
        fail_body = "".join(
            _row(feat, f"{n}x", "#f87171")
            for feat, n in sorted(failures.items(), key=lambda x: -x[1])
        )
        col_c += _card("Falhas", fail_body)

    if latency:
        lat_body = ""
        for feature, metrics in latency.items():
            for lbl, avg_s in metrics.items():
                step = lbl.replace("_avg_s", "").replace("_to_", " → ")
                lat_body += _row(f"{feature} {step}", _fmt_s(avg_s), "#38bdf8")
        if lat_body:
            col_c += _card("Latência", lat_body)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #13131f; color: #e0e0e0; font-family: 'Segoe UI', Arial, sans-serif; padding: 24px; width: 1080px; }}
  h1 {{ font-size: 18px; font-weight: 700; color: #fff; }}
  .sub {{ color: #666; font-size: 12px; margin-bottom: 20px; }}
  .tiles {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 18px; }}
  .cols {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; }}
</style>
</head>
<body>
  <h1>Relatório Semanal — {week}</h1>
  <div class="sub">{week_range}</div>
  <div class="tiles">{tiles_html}</div>
  <div class="cols">
    <div>{col_a}</div>
    <div>{col_b}</div>
    <div>{col_c}</div>
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

    html = _build_html(report)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1080, "height": 800})
        await page.set_content(html, wait_until="domcontentloaded")
        await page.wait_for_timeout(300)
        await page.screenshot(path=str(out_path), full_page=True)
        await browser.close()
