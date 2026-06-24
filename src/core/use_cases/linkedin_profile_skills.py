"""Domínio: lista desejada de competências LinkedIn e integração com skills_tracker."""

import json
from pathlib import Path

from src.config.settings import logger

_DESIRED_FILE = (
    Path(__file__).parent.parent.parent.parent / ".local" / "files" / "linkedin_desired_skills.json"
)


class LinkedInProfileSkills:
    """Gerencia a lista local de competências desejadas para o perfil LinkedIn."""

    def __init__(self, file_path: Path = _DESIRED_FILE) -> None:
        self._file = file_path

    def load(self) -> list[str]:
        """Carrega a lista desejada do arquivo local."""
        try:
            if self._file.exists():
                with open(self._file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return [s.strip() for s in data if isinstance(s, str) and s.strip()]
        except Exception as e:
            logger.warning(f"Could not load desired skills: {e}")
        return []

    def save(self, skills: list[str]) -> None:
        """Salva a lista desejada, deduplicando e preservando ordem."""
        unique = list(dict.fromkeys(s.strip() for s in skills if s.strip()))
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._file, "w", encoding="utf-8") as f:
                json.dump(unique, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved {len(unique)} desired LinkedIn skills")
        except Exception as e:
            logger.warning(f"Could not save desired skills: {e}")

    def add(self, skill: str) -> bool:
        """Adiciona uma skill à lista desejada. Retorna True se adicionada (era nova)."""
        skills = self.load()
        if any(s.lower() == skill.strip().lower() for s in skills):
            return False
        skills.append(skill.strip())
        self.save(skills)
        return True

    def remove(self, skill: str) -> bool:
        """Remove uma skill da lista desejada. Retorna True se removida."""
        skills = self.load()
        filtered = [s for s in skills if s.lower() != skill.strip().lower()]
        if len(filtered) == len(skills):
            return False
        self.save(filtered)
        return True

    @staticmethod
    def from_skills_tracker(top_n: int = 20) -> list[str]:
        """Retorna as top-N skills mais demandadas rastreadas pelo skills_tracker.

        Útil para sincronizar o perfil com as skills que os jobs exigem.
        """
        from src.core.use_cases.skills_tracker import load_skills

        skills = load_skills()
        if not skills:
            return []

        sorted_skills = sorted(skills.items(), key=lambda x: x[1].get("count", 0), reverse=True)
        return [name for name, _ in sorted_skills[:top_n]]
