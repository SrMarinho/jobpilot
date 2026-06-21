# Persistence

JobPilot stores all runtime state through a small persistence layer that has
**two interchangeable backends**, chosen at startup by a single env var:

| `DATABASE_URL` | Backend | Where data lives |
|---|---|---|
| empty / unset | **JSON** (default) | `.local/files/*.json` (atomic tmp+replace) |
| set | **Postgres** | managed Postgres (Neon/Supabase/…), direct psycopg/TLS |

The browser/bot always runs locally. Only the **data layer** can move to a remote
Postgres — useful for durability, ACID concurrency (no more lost updates when the
CLI and the Telegram bot write the same file), and SQL queries.

> Switch model: `DATABASE_URL` empty → JSON (today's behavior, unchanged).
> Set → Postgres. If Postgres is unreachable, commands **fail loudly** (single
> source of truth, no silent divergence). The bot needs connectivity in DB mode.

## Configuration

```bash
# .env  — use the pooled endpoint (pgbouncer) from your provider
DATABASE_URL=postgresql://user:pass@host:6543/dbname
```

`sslmode=require` is applied by default. psycopg is imported lazily, so the app
runs in JSON mode even without the driver installed. For DB mode:

```bash
uv add 'psycopg[binary]' psycopg-pool   # already in pyproject
```

## `db` commands

```bash
uv run main.py db check     # test connection, print server version
uv run main.py db init      # create schema (idempotent, CREATE TABLE IF NOT EXISTS)
uv run main.py db migrate   # one-shot: load .local/files/*.json into Postgres
uv run main.py db status    # row counts per table / kv namespace
```

`db migrate` reads the JSON files **directly from disk** (the trackers are
backend-aware and would otherwise read the empty DB) and is idempotent. The JSON
files are preserved, not deleted.

## Architecture

Two primitives in `src/core/persistence/` cover all 14 trackers — each tracker
only swaps its `_load`/`_save` (public APIs unchanged, call-sites untouched):

- **`db.py`** — lazy psycopg pool, `is_db_enabled()`, `init_schema()`, `ping()`.
- **`keyed_repo.py`** — `KeyedRepo(table, key_field)`: typed tables. Columns are
  derived from the record dict keys (which already match column names). Mutation
  = per-row `UPSERT` (the real ACID win for `applied_jobs`/`engaged_posts`/…).
- **`doc_repo.py`** — `DocRepo(ns, …)`: whole document as one JSONB row in
  `kv_store` (single-doc or multi-key, e.g. weekly reports). JSON mode reads/writes
  a file or a directory of files.
- **`migrate.py`** — `migrate_json_to_pg()` + `table_counts()`.

Key fact that keeps this low-risk: every tracker already loads its whole file
once into memory and mutates in RAM, so swapping `_load`/`_save` preserves the
**load-once** pattern — no per-item round trips, no latency regression.

### Hybrid schema

**Typed tables** (feed report/dashboard, benefit from SQL):
`applied_jobs`, `rejected_jobs`, `engaged_posts`, `profile_views`, `ssi_history`,
`skills_gap`, `connections_log`, `goals`.

**`kv_store(ns, key, val jsonb)`** (whole-doc, little querying / nested workflow):
`form_answers`, `saved_searches`, `engage_targets`, `last_urls`, `posted_history`,
`followup_dms`, `weekly_reports`, `engaged_meta` (self-author).

### Tracker → backend map

| Tracker | Repo | Table / ns |
|---|---|---|
| `AppliedJobsTracker` | KeyedRepo ×2 | `applied_jobs`, `rejected_jobs` |
| `EngagedPostsTracker` | KeyedRepo + DocRepo | `engaged_posts` + `engaged_meta` |
| `ProfileViewsTracker` / `SSITracker` | KeyedRepo | `profile_views` / `ssi_history` |
| `skills_tracker` | KeyedRepo | `skills_gap` |
| `GoalsTracker` | KeyedRepo | `goals` |
| `ReportRepository.connections_log` | KeyedRepo | `connections_log` |
| `FormAnswerCache` | DocRepo | `form_answers` |
| `SavedSearches` / `engage_targets` | DocRepo | `saved_searches` / `engage_targets` |
| `persistence.py` (last_urls) | DocRepo | `last_urls` |
| `PostedTracker` / `FollowupTracker` | DocRepo | `posted_history` / `followup_dms` |
| `ReportRepository` (weekly reports) | DocRepo (multi-key) | `weekly_reports` |

## Adding a new tracker

- Keyed (one record per id/date, feeds reports/queries): create a typed table in
  `db.py` `_SCHEMA`, use `KeyedRepo`, branch `_load`/mutations on `is_db_enabled()`.
- Document (whole blob, little querying): use `DocRepo(ns, json_file=…)` and just
  delegate `_load`/`_save` — both backends are transparent.
