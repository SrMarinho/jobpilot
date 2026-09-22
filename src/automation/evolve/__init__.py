"""Cura de selector com o browser na mão.

Fica em ``automation`` (e não em ``core/use_cases``) porque depende de
Playwright: descrever o DOM e validar um candidato exigem a página viva. O
resolvedor em ``pages/selectors.py`` só expõe o ponto de enxerto; a decisão e o
custo moram aqui.
"""

from .healer import HealBudget, SelectorHealer, install, uninstall

__all__ = ["HealBudget", "SelectorHealer", "install", "uninstall"]
