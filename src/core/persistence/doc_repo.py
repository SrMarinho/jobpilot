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

# Registro de docs que falharam ao gravar no Supabase e estão só no local,
# aguardando sync. O upsert kv_store é idempotente (ON CONFLICT), então
# re-sincronizar o mesmo doc é seguro (last-write-wins por ns/key).
_PENDING_FILE = Path(".local") / "files" / ".kv_pending.json"
_PENDING_SEP = "\x1f"


def _load_pending() -> dict:
    try:
        return json.loads(_PENDING_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_pending(d: dict) -> None:
    _PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PENDING_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_PENDING_FILE)


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
            try:
                with connection() as conn, dict_cursor(conn) as cur:
                    cur.execute(
                        "SELECT val FROM kv_store WHERE ns = %s AND key = %s",
                        (self.ns, key),
                    )
                    row = cur.fetchone()
                if row:
                    return row["val"]
                # DB ok mas sem linha: pode haver write local ainda não sincronizado.
                return self._read_local(key)
            except Exception as e:
                logger.warning(f"DB get falhou ({self.ns}/{key}), lendo local: {e}")
                return self._read_local(key)
        return self._read_local(key)

    def put(self, key: str, data: dict) -> None:
        if is_db_enabled():
            try:
                self._flush_pending()  # primeiro drena writes locais anteriores
                with connection() as conn:
                    conn.execute(_UPSERT, (self.ns, key, jsonb(data)))
                return
            except Exception as e:
                # Supabase indisponível: grava local + marca p/ sync futuro.
                logger.warning(
                    f"DB put falhou ({self.ns}/{key}), fallback local + pending: {e}"
                )
                if self._write_local(key, data):
                    self._mark_pending(key)
                else:
                    raise  # sem path local não há como cair de volta
                return
        self._write_local(key, data)

    # --- Local + pending-sync (fallback Supabase->local idempotente) ---
    def _read_local(self, key: str) -> dict | None:
        path = self._path(key)
        if path and path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning(f"Could not parse {path}, treating as empty")
        return None

    def _write_local(self, key: str, data: dict) -> bool:
        path = self._path(key)
        if path is None:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return True

    def _pending_id(self, key: str) -> str:
        return f"{self.ns}{_PENDING_SEP}{key}"

    def _mark_pending(self, key: str) -> None:
        p = _load_pending()
        p[self._pending_id(key)] = {"ns": self.ns, "key": key}
        _save_pending(p)

    def _flush_pending(self) -> None:
        """Reenvia ao Supabase os docs locais pendentes desta ns (idempotente)."""
        p = _load_pending()
        mine = {pid: m for pid, m in p.items() if m.get("ns") == self.ns}
        if not mine:
            return
        changed = False
        for pid, meta in mine.items():
            data = self._read_local(meta["key"])
            if data is None:
                p.pop(pid, None)
                changed = True
                continue
            try:
                with connection() as conn:
                    conn.execute(_UPSERT, (self.ns, meta["key"], jsonb(data)))
                p.pop(pid, None)
                changed = True
                logger.info(f"kv sync: {self.ns}/{meta['key']} -> Supabase")
            except Exception as e:
                logger.warning(f"kv sync falhou {self.ns}/{meta['key']}: {e}")
                break  # DB ainda fora; tenta de novo no próximo put
        if changed:
            _save_pending(p)

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
