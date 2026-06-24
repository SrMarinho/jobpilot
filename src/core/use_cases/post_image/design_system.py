"""Design system dos posts — TOKENS como dados portáveis.

O dict é o contrato: cores, fontes, assinatura, canvas. Estruturado plano de
propósito p/ depois virar uma linha num banco (ex: Supabase tabela
``post_design_systems``) sem refator — basta `json.dumps`/`from_dict`.

Hoje a fonte é este módulo (`DEFAULT_DESIGN_SYSTEM`). `load_design_system()` é a
costura única: quando houver banco, troca-se só o corpo dela (lê do Supabase),
APIs e schema idênticos.
"""

from __future__ import annotations

import copy
from pathlib import Path

from src.core.persistence.doc_repo import DocRepo

SCHEMA_VERSION = 1

# Namespace de persistência. Backend-aware via DocRepo: modo JSON grava em
# .local/files/design_systems/{id}.json; modo Postgres em kv_store ns
# 'design_systems'. Mesmo código, é a ponte p/ exportar ao Supabase.
_DS_NS = "design_systems"
_DS_DIR = Path(".local") / "files" / "design_systems"


def _repo() -> DocRepo:
    return DocRepo(_DS_NS, json_dir=_DS_DIR)


# Identidade: fundo escuro verde-grafite, accent verde-militar (exército),
# grid/linhas técnicas (vibe blueprint/engenharia), assinatura no rodapé.
DEFAULT_DESIGN_SYSTEM: dict = {
    "id": "military-grid",
    "name": "Military Grid",
    "schema_version": SCHEMA_VERSION,
    "canvas": {"width": 1080, "height": 1350},
    "colors": {
        "bg": "#0E1512",  # verde-grafite quase preto
        "bg2": "#16201A",  # degradê do fundo
        "grid": "rgba(120,150,110,0.07)",  # linhas técnicas sutis
        "accent": "#4B5320",  # verde-militar (army green) escuro
        "accent_soft": "#8A9A5B",  # sage p/ realce legível no escuro
        "text": "#EAF0EA",  # off-white
        "muted": "#93A08F",  # subtítulo/rodapé
    },
    "fonts": {
        "title": "'Inter', system-ui, -apple-system, 'Segoe UI', Arial, sans-serif",
        "mono": "'JetBrains Mono', ui-monospace, 'Cascadia Code', monospace",
        # <link> opcional do Google Fonts (Playwright tem rede). Com fallback.
        "google_href": (
            "https://fonts.googleapis.com/css2?"
            "family=Inter:wght@400;600;800&family=JetBrains+Mono:wght@400;600&display=swap"
        ),
    },
    "signature": {
        "name": "Matheus Marinho",
        "role": "Software Engineer",
    },
}


def load_design_system(ds_id: str = "military-grid") -> dict:
    """Retorna o design system por id (banco se DATABASE_URL setado, senão JSON).

    Fallback seguro: se não houver linha/arquivo, devolve o DEFAULT em código —
    sempre renderizável. Migrar p/ Supabase = só setar DATABASE_URL (o DocRepo
    passa a ler do kv_store), sem mudar este código.
    """
    stored = _repo().get(ds_id)
    if stored:
        return from_dict(stored)
    return copy.deepcopy(DEFAULT_DESIGN_SYSTEM)


def save_design_system(ds: dict) -> None:
    """Persiste o design system (upsert por id) no backend ativo."""
    _repo().put(ds["id"], to_dict(ds))


def seed_default() -> bool:
    """Grava o DEFAULT no backend se ainda não existir. Retorna True se semeou."""
    repo = _repo()
    if repo.exists(DEFAULT_DESIGN_SYSTEM["id"]):
        return False
    repo.put(DEFAULT_DESIGN_SYSTEM["id"], DEFAULT_DESIGN_SYSTEM)
    return True


def to_dict(ds: dict) -> dict:
    """Cópia serializável (pronta p/ `json.dumps` ou upsert no banco)."""
    return copy.deepcopy(ds)


def from_dict(data: dict) -> dict:
    """Reconstrói um design system a partir de dados (ex: linha do Supabase).

    Faz merge raso sobre o default p/ tolerar linhas parciais/versões antigas.
    """
    ds = copy.deepcopy(DEFAULT_DESIGN_SYSTEM)
    for key, val in (data or {}).items():
        if isinstance(val, dict) and isinstance(ds.get(key), dict):
            ds[key] = {**ds[key], **val}
        else:
            ds[key] = val
    return ds
