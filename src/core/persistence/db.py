"""Conexão Postgres (opcional). psycopg é importado lazy: o app roda em modo
JSON sem a dependência instalada. Só ao setar DATABASE_URL é que o pool sobe."""

from contextlib import contextmanager

from src.config import settings
from src.config.settings import logger

_pool = None  # psycopg_pool.ConnectionPool


def is_db_enabled() -> bool:
    """True quando DATABASE_URL está setado => backend Postgres."""
    return bool(settings.DATABASE_URL)


def _get_pool():
    global _pool
    if _pool is None:
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as e:
            raise RuntimeError(
                "DATABASE_URL setado mas 'psycopg[binary]' não está instalado. "
                "Rode: uv add 'psycopg[binary]' psycopg-pool"
            ) from e

        # prepare_threshold=None desliga prepared statements do psycopg3. O
        # pooler transaction (pgbouncer/6543) do Supabase reusa conexões e quebra
        # com "prepared statement already exists" se ficarem ligados.
        def _configure(conn):
            conn.prepare_threshold = None

        _pool = ConnectionPool(
            settings.DATABASE_URL,
            min_size=1,
            max_size=4,
            open=True,
            kwargs={"sslmode": "require"},
            configure=_configure,
        )
        logger.info("Postgres pool aberto")
    return _pool


@contextmanager
def connection():
    """Conexão do pool. Commit no sucesso / rollback na exceção (psycopg_pool)."""
    pool = _get_pool()
    with pool.connection() as conn:
        yield conn


@contextmanager
def dict_cursor(conn):
    """Cursor que retorna linhas como dict."""
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        yield cur


def jsonb(value):
    """Embrulha um valor Python para coluna JSONB."""
    from psycopg.types.json import Jsonb

    return Jsonb(value)


# DDL idempotente — híbrido: tabelas tipadas (report-feeders) + kv_store JSONB.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS applied_jobs (
    job_id text PRIMARY KEY,
    title text, company text, url text,
    applied_at timestamptz, salary_offered int, level text, site text, contract text
);
CREATE TABLE IF NOT EXISTS rejected_jobs (
    job_id text PRIMARY KEY,
    title text, url text, rejected_at timestamptz, reason text, site text
);
CREATE TABLE IF NOT EXISTS engaged_posts (
    urn text PRIMARY KEY,
    ts timestamptz, author text, actions jsonb, comment text, variant text,
    week text, month text, day text
);
CREATE TABLE IF NOT EXISTS profile_views (
    date date PRIMARY KEY,
    views int, ts timestamptz
);
CREATE TABLE IF NOT EXISTS search_appearances (
    date date PRIMARY KEY,
    count int, ts timestamptz
);
CREATE TABLE IF NOT EXISTS ssi_history (
    date date PRIMARY KEY,
    ts timestamptz, total real, brand real, find_people real,
    engage_insights real, relationships real,
    rank_industry_pct int, rank_network_pct int
);
CREATE TABLE IF NOT EXISTS skills_gap (
    skill text PRIMARY KEY,
    category text, level int, estimate text, count int,
    last_seen date, month_counts jsonb
);
CREATE TABLE IF NOT EXISTS connections_log (
    date date PRIMARY KEY,
    count int
);
CREATE TABLE IF NOT EXISTS goals (
    metric text PRIMARY KEY,
    target int
);
CREATE TABLE IF NOT EXISTS hired_profiles (
    profile_url text PRIMARY KEY,
    name text, headline text, company text,
    top_skills jsonb, age_days int, role text,
    source text, scraped_at timestamptz
);
CREATE TABLE IF NOT EXISTS kv_store (
    ns text, key text, val jsonb, updated_at timestamptz DEFAULT now(),
    PRIMARY KEY (ns, key)
);
CREATE INDEX IF NOT EXISTS idx_engaged_posts_week ON engaged_posts (week);
CREATE INDEX IF NOT EXISTS idx_applied_jobs_applied_at ON applied_jobs (applied_at);
"""


def init_schema() -> None:
    """Cria todas as tabelas/índices (idempotente)."""
    with connection() as conn:
        conn.execute(_SCHEMA)
    logger.info("Schema Postgres garantido (CREATE TABLE IF NOT EXISTS)")


def ping() -> str:
    """Testa conexão; retorna a versão do servidor."""
    with connection() as conn:
        row = conn.execute("SELECT version()").fetchone()
    return row[0] if row else "?"
