"""Identidade visual dos posts (design system) + render de card PNG.

Separado em DADOS (``design_system`` — tokens portáveis, mapeáveis 1:1 p/ uma
linha de banco tipo Supabase) e RENDER (``card_renderer`` — HTML+Playwright→PNG).
O app gera o card localmente, sem dependência de Canva/Enterprise.
"""

from src.core.use_cases.post_image.design_system import (
    DEFAULT_DESIGN_SYSTEM,
    load_design_system,
    save_design_system,
    seed_default,
)
from src.core.use_cases.post_image.card_renderer import (
    build_card_html,
    derive_card_copy,
    render_card_png,
)

__all__ = [
    "DEFAULT_DESIGN_SYSTEM",
    "load_design_system",
    "save_design_system",
    "seed_default",
    "build_card_html",
    "derive_card_copy",
    "render_card_png",
]
