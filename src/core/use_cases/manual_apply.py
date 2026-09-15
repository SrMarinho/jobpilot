"""Fila das vagas aprovadas que caíram em candidatura manual.

O arquivo já existia, mas só era escrito — 102 vagas que passaram na avaliação
do LLM, viraram um alerta no Telegram e morreram ali. Nenhum código o lia de
volta, e a URL guardada é sempre a do job board, nunca o formulário da empresa.

Aqui ele vira fila de trabalho: ``jobs apply-external`` lê a lista, e o link
externo resolvido na primeira visita fica gravado para a próxima.
"""

import json

from src.config.settings import files_dir, logger

MANUAL_FILE = files_dir / "manual_apply.json"


def load() -> dict:
    if not MANUAL_FILE.exists():
        return {}
    try:
        data = json.loads(MANUAL_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"manual_apply.json ilegível: {e}")
        return {}


def save(data: dict) -> None:
    MANUAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    MANUAL_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def add(job_url: str, entry: dict) -> bool:
    """Registra a vaga. ``False`` quando já estava na fila (evita alerta duplo)."""
    data = load()
    if job_url in data:
        return False
    data[job_url] = entry
    save(data)
    return True


def get(job_url: str) -> dict:
    return load().get(job_url, {})


def set_external_url(job_url: str, external_url: str) -> None:
    """Guarda o link do formulário da empresa resolvido a partir da vaga."""
    data = load()
    entry = data.get(job_url)
    if entry is None:
        entry = {}
        data[job_url] = entry
    entry["external_url"] = external_url
    save(data)


def mark_applied(job_url: str) -> None:
    """Tira da fila depois do envio — a fila é do que falta, não do histórico."""
    data = load()
    if data.pop(job_url, None) is not None:
        save(data)


def pending(limit: int | None = None) -> list[tuple[str, dict]]:
    """Vagas na fila, da mais recente para a mais antiga."""
    items = list(load().items())
    items.reverse()
    return items[:limit] if limit else items
