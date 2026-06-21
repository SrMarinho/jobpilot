"""Adapter Postgres p/ tabelas tipadas. Genérico: as colunas saem das chaves
do próprio record (que já batem com os nomes das colunas). Mutação = upsert por
linha (ganho de concorrência ACID vs reescrever arquivo inteiro).

Só é usado quando is_db_enabled(). Em modo JSON o tracker mantém seu IO de
arquivo original (sem regressão)."""

from datetime import date, datetime

from src.core.persistence.db import connection, dict_cursor, jsonb


def _adapt_in(value):
    """Python -> coluna. dict/list viram JSONB; resto passa direto (PG casta
    string ISO -> date/timestamptz)."""
    if isinstance(value, (dict, list)):
        return jsonb(value)
    return value


def _adapt_out(value):
    """Coluna -> Python, espelhando o que json.loads produziria (datas viram
    string ISO; jsonb já volta dict/list)."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _row_out(row: dict) -> dict:
    return {k: _adapt_out(v) for k, v in row.items()}


class KeyedRepo:
    def __init__(self, table: str, key_field: str):
        self.table = table
        self.key_field = key_field

    def all(self) -> list[dict]:
        with connection() as conn, dict_cursor(conn) as cur:
            cur.execute(f"SELECT * FROM {self.table}")  # noqa: S608 (nome fixo interno)
            return [_row_out(r) for r in cur.fetchall()]

    def upsert(self, record: dict) -> None:
        cols = list(record.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != self.key_field)
        sql = (
            f"INSERT INTO {self.table} ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({self.key_field}) DO UPDATE SET {updates}"
        )
        values = [_adapt_in(record[c]) for c in cols]
        with connection() as conn:
            conn.execute(sql, values)

    def delete(self, key) -> None:
        with connection() as conn:
            conn.execute(
                f"DELETE FROM {self.table} WHERE {self.key_field} = %s", (key,)
            )

    def replace_all(self, records: list[dict]) -> None:
        """Substitui o conteúdo inteiro da tabela (usado na migração)."""
        with connection() as conn:
            conn.execute(f"TRUNCATE {self.table}")
            for rec in records:
                cols = list(rec.keys())
                placeholders = ", ".join(["%s"] * len(cols))
                conn.execute(
                    f"INSERT INTO {self.table} ({', '.join(cols)}) "
                    f"VALUES ({placeholders})",
                    [_adapt_in(rec[c]) for c in cols],
                )

    def count(self) -> int:
        with connection() as conn:
            row = conn.execute(f"SELECT count(*) FROM {self.table}").fetchone()
        return row[0] if row else 0
