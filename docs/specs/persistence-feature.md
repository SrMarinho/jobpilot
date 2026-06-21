# Spec — Camada de persistência (JSON ↔ Postgres)

## 1. Problema

Os 14 trackers guardavam estado em ~15 arquivos JSON (`.local/files/`), via
read-modify-write do arquivo inteiro. Limitações:

1. **Sem durabilidade** — dados morrem com a máquina.
2. **Lost update** — CLI e bot-runner escrevem o mesmo arquivo; o browser-lock
   serializa só o navegador, não as escritas de JSON.
3. **Sem query** — report/dashboard carregam o JSON e filtram em Python.

O bot continua rodando **localmente** (LinkedIn logado, Chrome profile, creds na
máquina). Só a **camada de dados** pode ir para um Postgres gerenciado remoto.

## 2. Decisões

- **Engine:** Postgres, **híbrido** — tabelas tipadas para os que alimentam
  report/dashboard + `kv_store` JSONB para o resto.
- **Switch por env:** `DATABASE_URL` vazio → JSON (comportamento atual, intacto);
  setado → Postgres. PG inacessível → **erro claro** (fonte de verdade única, sem
  divergência). Sem dual-write/offline-sync.
- **Driver:** psycopg 3 + pool, importado lazy (app roda em modo JSON sem a dep).
  Schema via `CREATE TABLE IF NOT EXISTS` (sem ORM/Alembic).
- **Conexão direta** TCP/TLS da máquina ao Postgres (cliente confiável, sem API
  intermediária), endpoint pooled (pgbouncer), `sslmode=require`.

## 3. Arquitetura

`src/core/persistence/`:

| Arquivo | Papel |
|---|---|
| `db.py` | pool lazy, `is_db_enabled()`, `init_schema()`, `ping()`, DDL |
| `keyed_repo.py` | `KeyedRepo(table, key_field)` — tabelas tipadas; colunas saem das chaves do record; mutação = upsert por linha (ACID) |
| `doc_repo.py` | `DocRepo(ns, …)` — doc inteiro em `kv_store` (single ou multi-key); modo JSON = arquivo/pasta |
| `migrate.py` | `migrate_json_to_pg()` (lê JSON do disco → PG, idempotente) + `table_counts()` |

**Chave de baixo risco:** todo tracker já carrega o arquivo inteiro 1× em memória
e muta em RAM. Trocando só `_load`/`_save`, preserva-se o padrão **load-once** —
sem round-trip por item, APIs públicas e call-sites intactos.

### Split do schema

- **Tipadas:** `applied_jobs`, `rejected_jobs`, `engaged_posts`, `profile_views`,
  `ssi_history`, `skills_gap`, `connections_log`, `goals`.
- **`kv_store(ns,key,val jsonb)`:** `form_answers`, `saved_searches`,
  `engage_targets`, `last_urls`, `posted_history`, `followup_dms`,
  `weekly_reports`, `engaged_meta` (self-author).

`form_answers` ficou em kv (não tipado) por ter valor heterogêneo (string OU dict)
e ser escrito sob browser-lock — parità exata sem drift.

## 4. CLI

```bash
uv run main.py db check     # testa conexão + versão
uv run main.py db init      # cria schema (idempotente)
uv run main.py db migrate   # sobe os .local/files/*.json para o PG (idempotente)
uv run main.py db status    # contagem por tabela / namespace kv
```

## 5. Verificação

**Modo JSON (sem `DATABASE_URL`):** todos os trackers carregam os JSON existentes
idênticos a antes (regressão), `ruff check` limpo.

**Modo Postgres (ao plugar a URL):** `db check` conecta; `db init` cria schema
(roda 2× sem erro); `db migrate` sobe os JSON; `db status` mostra contagens;
`profile-views show`/`report` leem do PG. URL inválida com `DATABASE_URL` setado →
erro claro (não inicia silenciosamente).

## 6. Não-escopo / futuro

- Rodar o bot em cloud/outra máquina; persistir sessão do Chrome; proxy residencial.
- Dual-write / offline-sync (descartado: switch por env).
- Reescrever report/dashboard para usar SQL nativo (hoje leem via repos em memória).
- Migrar para SQLAlchemy/ORM.
