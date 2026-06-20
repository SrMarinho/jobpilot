"""Meta semanal + alerta.

Define alvos semanais (candidaturas, conexões, posts, comentários). O
relatório semanal cruza com o realizado e avisa o que está atrás. Apenas
configuração persistida — o cálculo do realizado vive no report package.
"""

import json
from pathlib import Path

from src.config.settings import logger

_FILES_DIR = Path(".local") / "files"
GOALS_FILE = _FILES_DIR / "goals.json"

# Metas suportadas e seus rótulos no relatório.
GOAL_KEYS = ("applications", "connections", "posts", "comments")

_DEFAULTS = {
    "applications": 10,
    "connections": 50,
    "posts": 2,
    "comments": 6,
}


class GoalsTracker:
    def __init__(self, path: Path = GOALS_FILE):
        self._path = path
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning(f"Could not parse {self._path}, using defaults")
        return {}

    def _save(self) -> None:
        _FILES_DIR.mkdir(exist_ok=True, parents=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self._path)

    def get(self, key: str) -> int:
        return int(self._data.get(key, _DEFAULTS.get(key, 0)))

    def all(self) -> dict:
        return {k: self.get(k) for k in GOAL_KEYS}

    def set(self, key: str, value: int) -> None:
        if key not in GOAL_KEYS:
            raise ValueError(f"meta desconhecida: {key} (use {', '.join(GOAL_KEYS)})")
        self._data[key] = int(value)
        self._save()
        logger.info(f"Meta semanal definida: {key}={value}")
