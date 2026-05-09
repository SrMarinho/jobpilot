# Architecture

JobPilot follows a layered architecture with clear separation between CLI, orchestration, page objects, and business logic.

## Layer stack

```
CLI (main.py, Typer)
  └─ Orchestration (src/automation/tasks/)
       ├─ Site pages (src/automation/pages/)
       └─ Business logic (src/core/use_cases/)
            └─ AI providers (src/core/ai/)
```

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

### Orchestration (`src/automation/tasks/`)

| File | Responsibility |
|------|---------------|
| `job_application_manager.py` | Page/card loop, site detection, pagination, lifecycle |
| `connection_manager.py` | People search page loop, invite lifecycle |

### Business logic (`src/core/use_cases/`)

| File | Responsibility |
|------|---------------|
| `job_evaluator.py` | Quick rejects (title, language, tech) + AI evaluation (single LLM call) |
| `job_application_handler.py` | LinkedIn/Glassdoor Easy Apply form filling (multi-step) |
| `indeed_application_handler.py` | Indeed apply form filling |
| `applied_jobs_tracker.py` | JSON-backed deduplication (applied_jobs.json, rejected_jobs.json) |
| `skills_tracker.py` | Tracks missing skills from rejections, AI-categorizes by type and difficulty |
| `salary_estimator.py` | AI salary estimation from job description and market data |
| `invitation_handler.py` | LinkedIn connection invite sending |
| `monthly_report.py` | Aggregates applied/rejected/connections per month |

### AI providers (`src/core/ai/`)

| Provider | Backend | Model |
|----------|---------|-------|
| `ClaudeProvider` | claude-agent-sdk (Claude Code) | claude-haiku-4-5-20251001 |
| `LangChainProvider` | Ollama (local) | Any Ollama model |

Two independent providers: `LLM_PROVIDER` (form Q&A, cheaper) and `LLM_PROVIDER_EVAL` (job evaluation, smarter).

### URL builder (`src/automation/url_builder.py`)

Converts CLI flags to search URLs for LinkedIn and Indeed. Glassdoor uses raw `--url` (URL structure too complex for builder).

### Bot (`src/bot/`)

Telegram long-polling bot. Runs the same orchestrators in background threads with a shared `stop_event`.

### Utils (`src/utils/`)

`telegram.py` — Telegram message sending helper (used by bot and report).

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
