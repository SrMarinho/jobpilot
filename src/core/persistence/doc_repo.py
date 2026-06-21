"""Doc inteiro em kv_store (val JSONB). Para trackers com pouca query e/ou
workflow aninhado (saved_searches, posted_history, etc). Single-doc (key='_')
ou multi-key (ex: weekly_reports por week).

Só é usado quando is_db_enabled(). Em modo JSON usa arquivo (single) ou pasta
de arquivos (multi)."""

import json
from pathlib import Path

from src.config.settings import logger
from src.core.persistence.db import connection, dict_cursor, is_db_enabled, jsonb

_UPSERT = (
    "INSERT INTO kv_store (ns, key, val, updated_at) VALUES (%s, %s, %s, now()) "
    "ON CONFLICT (ns, key) DO UPDATE SET val = EXCLUDED.val, updated_at = now()"
)


class DocRepo:
    def __init__(
        self,
        ns: str,
        *,
        json_file: str | Path | None = None,
        json_dir: str | Path | None = None,
        default_key: str = "_",
    ):
        self.ns = ns
        self.json_file = Path(json_file) if json_file else None
        self.json_dir = Path(json_dir) if json_dir else None
        self.default_key = default_key

    # --- API single-doc ---
    def load(self) -> dict:
        return self.get(self.default_key) or {}

    def save(self, data: dict) -> None:
        self.put(self.default_key, data)

    # --- API por chave ---
    def get(self, key: str) -> dict | None:
        if is_db_enabled():
            with connection() as conn, dict_cursor(conn) as cur:
                cur.execute(
                    "SELECT val FROM kv_store WHERE ns = %s AND key = %s",
                    (self.ns, key),
                )
                row = cur.fetchone()
                return row["val"] if row else None
        path = self._path(key)
        if path and path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning(f"Could not parse {path}, treating as empty")
        return None

    def put(self, key: str, data: dict) -> None:
        if is_db_enabled():
            with connection() as conn:
                conn.execute(_UPSERT, (self.ns, key, jsonb(data)))
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def exists(self, key: str) -> bool:
        if is_db_enabled():
            with connection() as conn:
                row = conn.execute(
                    "SELECT 1 FROM kv_store WHERE ns = %s AND key = %s",
                    (self.ns, key),
                ).fetchone()
                return row is not None
        path = self._path(key)
        return bool(path and path.exists())

    def _path(self, key: str) -> Path | None:
        if self.json_file is not None:
            return self.json_file
        if self.json_dir is not None:
            return self.json_dir / f"{key}.json"
        return None
