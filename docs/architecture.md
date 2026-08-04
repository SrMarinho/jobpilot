# Architecture

JobPilot follows a layered architecture with clear separation between CLI, orchestration, page objects, and business logic.

## Layer stack

```
CLI (main.py, Typer)
  ├─ profile capture/skills/views/ssi/appearances  ← profile group
  └─ Orchestration (src/automation/tasks/)
       ├─ Site pages (src/automation/pages/)
       └─ Business logic (src/core/use_cases/)
            ├─ AI providers (src/core/ai/)
            └─ Entities (src/core/entities/)     ← camada mais interna
```

A dependência aponta sempre pra dentro: `entities` não importa nada do projeto,
`use_cases` importa `entities`, `automation` importa `use_cases`, e a CLI importa
tudo. `src/core/entities/` guarda `EvalResult` (veredito do LLM sobre uma vaga) e
`AppliedJob`/`RejectedJob` (registro de candidatura, cujo `as_record()` é o único
lugar que mapeia entidade → coluna do banco).

`src/config/` é infraestrutura (env, logger); `src/core/config/` é política de
negócio parametrizável (ex.: faixas salariais do prompt de avaliação).

## Request flow (apply)

```
User CLI
  → main.py:apply() resolves URL/search params
  → JobApplicationManager.run()
    → loop pages:
      → page.get_job_cards()
      → for each card:
        → page.get_job_title()
        → page.get_job_description()
        → tracker.already_applied() / already_rejected()
        → evaluator.quick_reject() (title seniority, no LLM)
        → evaluator.language_reject() (non-PT, no LLM)
        → evaluator.tech_reject() (stack mismatch, no LLM)
        → evaluator.evaluate() (single LLM call: match, salary, reason, skills)
        → page.get_apply_btn()
        → handler.submit_easy_apply()
          → per step:
            → collect unfilled fields
            → form_answers.json cache lookup
            → single LLM batch for uncached questions
            → fill fields + validate
            → click next or submit
        → tracker.mark_applied() or mark_rejected()
        → skills_tracker.track_missing_skills()
```

## Key components

### Page objects (`src/automation/pages/`)

Implement site-specific selectors and interaction:

| File | Site | Methods |
|------|------|---------|
| `jobs_search_page.py` | LinkedIn | `get_job_cards`, `get_job_title`, `get_job_description`, `get_easy_apply_btn`, `get_card_job_url`, `get_company_name` |
| `glassdoor_jobs_page.py` | Glassdoor | Same interface + `close_modal`, `get_card_job_id`, `next_page_url` |
| `indeed_jobs_page.py` | Indeed | Same + `get_card_job_url`, `next_page_url` |
| `people_search_page.py` | LinkedIn people | `get_connections_btn`, `send_without_note` |
| `linkedin_skills_page.py` | LinkedIn profile | `list_skills`, `add_skill`, `delete_skill` |
| `profile_views_page.py` | LinkedIn analytics | `scrape_with_goto` → int (90d views) |
| `search_appearances_page.py` | LinkedIn analytics | `scrape_with_goto` → int (weekly count) |
| `ssi_page.py` | LinkedIn SSI | `scrape_with_goto` → dict (total + 4 pillars + ranks) |

### Orchestration (`src/automation/tasks/`)

| File | Responsibility |
|------|---------------|
| `job_application_manager.py` | Page/card loop, site detection, pagination, lifecycle |
| `connection_manager.py` | People search page loop, invite lifecycle |
| `linkedin_skills_manager.py` | Add/delete/sync LinkedIn profile skills (wraps `LinkedInSkillsPage`) |

### Business logic (`src/core/use_cases/`)

| File | Responsibility |
|------|---------------|
| `job_evaluator.py` | Quick rejects (title, language, tech) + AI evaluation. `_build_prompt` serve single e batch — um prompt só, `EvalResult` de retorno |
| `apply/` | Easy Apply do LinkedIn/Glassdoor, quatro responsabilidades separadas (ver abaixo) |
| `indeed_application_handler.py` | Indeed apply form filling (reusa `FormAnswerer`/`FieldFiller`) |
| `applied_jobs_tracker.py` | Deduplication, backend-aware (JSON or Postgres) |
| `skills_tracker.py` | Tracks missing skills from rejections, AI-categorizes by type and difficulty |
| `linkedin_profile_skills.py` | Desired LinkedIn profile skills: load/save/diff + `from_skills_tracker()` |
| `ssi_tracker.py` | Daily SSI snapshots (JSON or Postgres); weekly lookup for report |
| `profile_views_tracker.py` | Daily profile-views snapshots; trend + acceleration analysis |
| `search_appearances_tracker.py` | Daily search-appearance snapshots; trend delta |
| `salary_estimator.py` | AI salary estimation from job description and market data |
| `invitation_handler.py` | LinkedIn connection invite sending |
| `monthly_report.py` | Aggregates applied/rejected/connections per month |

#### Easy Apply (`src/core/use_cases/apply/`)

Quatro peças compostas — não herdadas — pelo orquestrador:

| Módulo | Responsabilidade |
|--------|-----------------|
| `form_answerer.py` | Decide **o que** responder: cache primeiro, LLM depois. Sem DOM — por isso o Indeed reusa |
| `field_filler.py` | Sabe **como** escrever num campo e descobrir seu rótulo. Sem LLM |
| `modal_driver.py` | Abre, espera, inspeciona e fecha o modal do Easy Apply |
| `easy_apply.py` | `EasyApplyHandler`: o loop de etapas do formulário até enviar |

### Selectors (`src/automation/pages/selectors.py`)

Cada campo de uma page é declarado como **lista de candidatos** em ordem de
preferência; `first_visible` / `first_enabled` / `text_or_empty` resolvem o
primeiro que aparece. Quando nenhum casa, sai um WARNING nomeado (`campo=...`)
em vez de string vazia silenciosa — é o sinal de que o layout do site mudou.

Timeouts são nomeados (`T_FAST`, `T_NORMAL`, `T_SLOW`), não números soltos.

> Nunca use `locator("a, b")` pra fazer fallback: isso casa os **dois**
> seletores e estoura strict mode quando ambos existem na página.

### AI providers (`src/core/ai/`)

| Provider | Backend | Model |
|----------|---------|-------|
| `ClaudeProvider` | claude-agent-sdk (Claude Code) | claude-haiku-4-5-20251001 |
| `LangChainProvider` | Ollama (local) | Any Ollama model |

Two independent providers: `LLM_PROVIDER` (form Q&A, cheaper) and `LLM_PROVIDER_EVAL` (job evaluation, smarter).

### URL builder (`src/automation/url_builder.py`)

Converts CLI flags to search URLs for LinkedIn and Indeed. Glassdoor uses raw `--url` (URL structure too complex for builder).

### Bot (`src/bot/`)

Telegram long-polling bot. Runs the same orchestrators in background threads with
a shared `stop_event`. Detalhes em [bot.md](bot.md).

### Config (`src/config/`)

`env.py` lê env de forma tipada (`env_str`/`env_int`/`env_bool`/`env_required`),
sempre **no momento do acesso** — o bot ajusta `os.environ` em runtime, então um
valor congelado no import seria ignorado. `sections.py` agrupa por domínio
(`telegram`, `user`, `engage`, `autopost`), e é onde se descobre que variáveis
existem sem varrer o código.

### Utils (`src/utils/`)

`telegram.py` — envio pro Telegram. Um único `_post()` com `raise_for_status` e
retry com backoff em 429/5xx. Notificações são fire-and-forget: chamadas de dentro
de corrotina, vão pra uma thread em vez de travar o event loop (e com ele o
browser) pelo tempo do POST.

### Persistence (`src/core/persistence/`)

All 14 trackers persist through a backend-swappable layer selected by the
`DATABASE_URL` env var: **JSON** files (`.local/files/`, default) or **Postgres**
(managed, remote). Two primitives — `KeyedRepo` (typed tables, per-row upsert) and
`DocRepo` (whole-doc JSONB in `kv_store`) — back every tracker; each tracker only
swaps its `_load`/`_save`, keeping public APIs and call-sites unchanged.

`DailySnapshotTracker` é a base dos trackers de um-registro-por-dia (SSI,
profile views, search appearances): subclasses só declaram a tabela e o payload
do dia. CLI: `db check|init|migrate|status`. Full details in
[persistence.md](persistence.md).

## Adding a new job board

1. Create `XxxJobsPage` in `src/automation/pages/` implementing:
   - `get_job_cards()` → list of card elements
   - `get_job_title()` → string
   - `get_job_description()` → string
   - `get_apply_btn()` → element or None
   - `get_card_job_url(card)` → string (for dedup)
   - `next_page_url(base_url, page_num)` → string (for Indeed/Glassdoor-style)

2. Add branch in `JobApplicationManager.__init__`:
   ```python
   elif self.site == "mysite":
       self.page = MysiteJobsPage(driver, url)
       self.PAGE_SIZE = N
   ```

3. (Optional) If form flow differs, create `MysiteApplicationHandler`.

4. Add site to `_detect_site()` in `job_application_manager.py`.

5. Add URL builder for the site in `url_builder.py`.

Core components (`JobEvaluator`, `AppliedJobsTracker`, `SkillsTracker`) work unchanged.
