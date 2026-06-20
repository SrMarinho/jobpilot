"""Lista de empresas/pessoas-alvo do engage.

Engajar com a rede relevante (empresas-alvo) pesa mais no SSI do que
comentar no feed aleatório. Aqui só persiste/serve a lista de termos-alvo
(nomes de empresa ou pessoa); o filtro vive no EngagementManager.
"""

import json
from pathlib import Path

from src.config.settings import logger

_FILES_DIR = Path(".local") / "files"
ENGAGE_TARGETS_FILE = _FILES_DIR / "engage_targets.json"


def load_targets() -> list[str]:
    if ENGAGE_TARGETS_FILE.exists():
        try:
            data = json.loads(ENGAGE_TARGETS_FILE.read_text(encoding="utf-8"))
            return [t for t in data.get("targets", []) if t]
        except Exception:
            logger.warning(f"Could not parse {ENGAGE_TARGETS_FILE}")
    return []


def save_targets(targets: list[str]) -> None:
    _FILES_DIR.mkdir(exist_ok=True, parents=True)
    clean = sorted({t.strip() for t in targets if t and t.strip()})
    tmp = ENGAGE_TARGETS_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"targets": clean}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp.replace(ENGAGE_TARGETS_FILE)
    logger.info(f"Engage targets salvos: {len(clean)}")


def matches_target(author: str, text: str, targets: list[str]) -> bool:
    """True se o autor ou o texto do post menciona algum alvo."""
    if not targets:
        return True  # sem alvos = engage normal (qualquer post relevante)
    hay = f"{author}\n{text}".lower()
    return any(t.lower() in hay for t in targets)
