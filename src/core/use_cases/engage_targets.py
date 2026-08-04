"""Lista de empresas/pessoas-alvo do engage.

Engajar com a rede relevante (empresas-alvo) pesa mais no SSI do que
comentar no feed aleatório. Aqui só persiste/serve a lista de termos-alvo
(nomes de empresa ou pessoa); o filtro vive no EngagementManager.
"""

from src.config.settings import files_dir, logger
from src.core.persistence.doc_repo import DocRepo

ENGAGE_TARGETS_FILE = files_dir / "engage_targets.json"


def _doc() -> DocRepo:
    return DocRepo("engage_targets", json_file=ENGAGE_TARGETS_FILE)


def load_targets() -> list[str]:
    data = _doc().load()
    return [t for t in data.get("targets", []) if t]


def save_targets(targets: list[str]) -> None:
    clean = sorted({t.strip() for t in targets if t and t.strip()})
    _doc().save({"targets": clean})
    logger.info(f"Engage targets salvos: {len(clean)}")


def matches_target(author: str, text: str, targets: list[str]) -> bool:
    """True se o autor ou o texto do post menciona algum alvo."""
    if not targets:
        return True  # sem alvos = engage normal (qualquer post relevante)
    hay = f"{author}\n{text}".lower()
    return any(t.lower() in hay for t in targets)
