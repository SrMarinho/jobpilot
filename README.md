# JobPilot

Automated job application bot with AI-powered evaluation. Currently supports LinkedIn (Easy Apply + connection requests), with an architecture designed to add new job boards.

## Features

- **Apply** — Evaluates jobs against your resume and applies automatically
  - Built-in URL builder: `--keywords "python" --date-posted 24h` instead of pasting search URLs
  - Multi-site: LinkedIn, Glassdoor, Indeed
  - Filters by language (pt-BR by default) and seniority level
  - AI estimates salary expectation based on job description and market data
  - Answers custom form questions using LLM (cached in `files/form_answers.json`)
  - Tracks applied and rejected jobs to avoid duplicates across runs
  - Resume from interruption: `--continue` picks up at the last page
- **Connect** — Sends LinkedIn connection requests automatically
  - Built-in search: `--keywords "tech recruiter" --network S`
  - Scheduled mode: runs once per day, respects weekly invite limits
- **Search Builder** — Build LinkedIn/Indeed search URLs from CLI flags instead of pasting URLs
- **Skills Tracker** — Identifies missing skills rejected by AI evaluations (`skills list` / `skills top`)
- **Provider** — Switch AI backends at runtime (`provider set eval claude`)
- **Answers** — Pre-fill form answers manually to skip redundant LLM calls (`answers fill`)
- **Bot** — Control JobPilot remotely via Telegram bot
- **Report** — Monthly statistics: applications, rejections, skills gap, salary averages
- **Scheduled Tasks** — Windows Task Scheduler integration for fully automated daily runs
- **test-apply** — Dry-run Easy Apply on a single job URL without evaluation

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Google Chrome
- Account already logged in on Chrome
- Claude Code with Pro plan (used by the AI evaluator)

## Installation

```bash
git clone https://github.com/SrMarinho/jobpilot.git
cd jobpilot
uv sync
```

## Configuration

Create a `.env` file at the project root:

```env
HEADLESS=FALSE

# Telegram (optional — required for bot mode and notifications)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_channel_id   # channel/group for notifications
TELEGRAM_ADMIN_ID=your_personal_id # your personal chat ID for commands

# LLM provider: "claude" or "langchain" (Ollama)
LLM_PROVIDER=langchain
CLAUDE_MODEL=claude-haiku-4-5-20251001
LANGCHAIN_MODEL=deepseek-r1:14b        # recommended local model
LANGCHAIN_BASE_URL=http://localhost:11434

# Separate provider for job evaluation (optional, falls back to LLM_PROVIDER)
LLM_PROVIDER_EVAL=langchain
LANGCHAIN_MODEL_EVAL=deepseek-r1:14b   # recommended local model
```

> Set `HEADLESS=TRUE` to run Chrome in the background (no visible window).

To get your `TELEGRAM_ADMIN_ID`, send any message to your bot and open:
```
https://api.telegram.org/bot<TOKEN>/getUpdates
```
Your `chat.id` will appear in the response.

## Login

Before running any task, log in to LinkedIn (or other supported sites) once so the session is saved to the browser profile:

```bash
# Log in (browser opens — log in manually, then close)
uv run main.py login linkedin
uv run main.py login glassdoor
uv run main.py login indeed

# Log out (clears cookies for that site)
uv run main.py logout linkedin
```

A browser window will open. Log in normally, then close it. The session is persisted in `bot_profile/` and reused on every subsequent run.

To switch accounts or clear a session, use `logout <site>`.

## Quick Reference

| Command | Purpose |
|---------|---------|
| `login <site>` | Open browser to log in to linkedin/glassdoor/indeed |
| `logout <site>` | Clear saved session for a site |
| `apply` | Apply to jobs (search by keywords or URL) |
| `connect` | Send LinkedIn connection requests |
| `test-apply <url>` | Dry-run Easy Apply on a single job (no AI evaluation) |
| `bot` | Start Telegram bot for remote control |
| `provider show/set` | View or change LLM backends |
| `answers list/show/set/fill/clear` | Manage cached form answers |
| `skills list/top/clear` | View missing skills detected by AI |
| `report` | Monthly statistics and reports |

## Usage

> **Tip:** Use `--keywords` and filters to search without building URLs manually. Search params are saved per site in `files/last_urls.json` and restored on future runs. The old `--url` mode still works for raw URLs or Glassdoor.

---

### Apply to jobs

```bash
# First run — keywords required
uv run main.py apply --keywords "python developer" --site linkedin --resume "resume.pdf" --workplace remote --date-posted 24h

# Subsequent runs — reuses last saved search params
uv run main.py apply

# Resume from the last page where it stopped
uv run main.py apply --continue

# Resume a specific site's saved config
uv run main.py apply --continue --site indeed

# Raw URL fallback (still supported)
uv run main.py apply --url "JOB_SEARCH_URL" --resume "path/to/resume.pdf"
```

All parameters are saved per site (`apply_linkedin`, `apply_indeed`, `apply_glassdoor`) and restored automatically on the next run.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--url` | First run* | Full search URL (overrides `--keywords`) |
| `--keywords` `-k` | First run* | Search terms (e.g. `'python backend'`) |
| `--date-posted` | No | Filter: `24h`, `week`, `month`, `any` |
| `--workplace` | No | Filter: `on-site`, `remote`, `hybrid` |
| `--location` | No | Location filter (e.g. `'Brasil'`) |
| `--experience` | No | Level: `internship`, `entry`, `associate`, `mid-senior`, `director`, `executive` |
| `--resume` `-r` | No | Path to resume PDF or TXT (default: `resume.txt`) |
| `--preferences` `-p` | No | Preferences to guide evaluation |
| `--level` `-l` | No | Seniority level filter (repeat: `--level junior --level pleno`) |
| `--max-pages` | No | Max pages to process (default: 100) |
| `--max-applications` | No | Stop after N applications (default: unlimited) |
| `--no-save` | No | Run without overwriting the saved config |
| `--no-submit` | No | Fill forms but do not submit (for testing) |
| `--site` | No | Target site: `linkedin`, `glassdoor`, `indeed` |
| `--eval-provider` | No | Override eval AI: `claude` or `langchain` |
| `--eval-model` | No | Override eval model for this run |
| `--llm-provider` | No | Override form Q&A AI: `claude` or `langchain` |
| `--llm-model` | No | Override form Q&A model for this run |

> \* Either `--url` or `--keywords` is required on first run. Easy Apply (`f_AL=true`) is always enabled automatically.

**Example (LinkedIn):**
```bash
uv run main.py apply \
  --keywords "python developer" \
  --site linkedin \
  --workplace remote \
  --date-posted 24h \
  --location Brasil \
  --resume "resume.pdf" \
  --preferences "Python ou Node.js backend, remoto, apenas vagas em português" \
  --level junior --level pleno \
  --eval-provider langchain
```

---

### Send connection requests (LinkedIn)

```bash
# First run — keywords required
uv run main.py connect --keywords "tech recruiter" --network S

# Subsequent runs — reuses last saved search
uv run main.py connect

# Resume from the last page where it stopped
uv run main.py connect --continue

# Raw URL fallback
uv run main.py connect --url "PEOPLE_SEARCH_URL"
```

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--url` `-u` | First run* | Full LinkedIn people search URL |
| `--keywords` `-k` | First run* | Search terms (e.g. `'tech recruiter'`) |
| `--network` | No | Connection degree: `F`=1st, `S`=2nd, `O`=3rd+ |
| `--start-page` | No | Page to start from (default: 1) |
| `--max-pages` | No | Max pages to process (default: 100) |
| `--continue` | No | Resume from the last page where the previous run stopped |

> \* Either `--url` or `--keywords` is required on first run.

> The current page is saved in real time as the bot runs. If execution is interrupted, `--continue` picks up exactly where it left off.

---

### Switch AI provider

View the current configuration or switch backends without editing `.env` manually:

```bash
# Show current providers
uv run main.py provider show

# Use Claude for job evaluation
uv run main.py provider set eval claude

# Use Ollama for job evaluation
uv run main.py provider set eval langchain --model llama3.1:8b

# Use Claude for form Q&A
uv run main.py provider set llm claude

# Use a specific Claude model
uv run main.py provider set eval claude --model claude-opus-4-6
```

| Target | Description |
|--------|-------------|
| `eval` | AI used to evaluate whether a job matches your resume |
| `llm` | AI used to answer unknown form questions |

> Changes are written directly to `.env` and take effect on the next run.

---

### Manage form answers

JobPilot caches answers to form questions in `files/form_answers.json` so it doesn't need to call the AI repeatedly. Use the `answers` command to inspect and edit this cache:

```bash
# Show questions with missing answers (numbered)
uv run main.py answers list

# Show all cached answers
uv run main.py answers show

# Set an answer by number (from list or show)
uv run main.py answers set 15 "25"

# Answer all missing questions interactively
uv run main.py answers fill

# Clear all cached answers
uv run main.py answers clear
```

> If a required field has no answer (cache miss and AI doesn't know), the application is automatically aborted for that job.

---

### Telegram Bot

Start the bot to control JobPilot remotely via Telegram:

```bash
uv run main.py bot
```

| Command | Description |
|---------|-------------|
| `/connect` | Start sending connection requests (bot will ask for the URL) |
| `/apply <url>` | Start applying to jobs |
| `/status` | Check if a task is running |
| `/stop` | Stop the current task |
| `/resume` | Upload a new resume file (PDF or TXT) |
| `/ping` | Check if the bot is alive |
| `/reiniciar` | Restart the bot process |
| `/help` | List all commands |

The bot sends a Telegram notification to your channel every time an application is submitted.

---

### Monthly report

Prints a summary to the terminal. Use `--telegram` to also send via Telegram.

```bash
# Current month (default)
uv run main.py report

# Previous month
uv run main.py report --prev

# Specific month
uv run main.py report --month 2026-03

# Annual summary
uv run main.py report --year 2026

# Any of the above + send via Telegram
uv run main.py report --telegram
uv run main.py report --prev --telegram

# Scheduled mode: sends via Telegram only once per month, skips if already sent
uv run main.py report --scheduled
```

The report includes: applications sent, connections made, rejection breakdown by reason, seniority level breakdown, match rate, average estimated salary, top skills that blocked jobs this month, and evolution vs the previous month (↑/↓).

Reports are saved to `files/monthly_reports/YYYY-MM.json` for historical reference.

---

### Skills tracking

JobPilot tracks skills that are flagged as missing during AI job evaluation. This helps you identify what to learn next based on real market demands.

```bash
# List all missing skills sorted by demand frequency
uv run main.py skills list

# Filter by category
uv run main.py skills list --category python

# Filter by learning difficulty (1=days, 5=1+ year)
uv run main.py skills list --level 3

# Show top N most demanded skills
uv run main.py skills top --n 15

# Clear all tracked skills
uv run main.py skills clear
```

Each skill entry includes:
- **Category**: python, node, frontend, devops, data, general
- **Level**: estimated learning time (1=dias, 2=semanas, 3=1-3 meses, 4=3-12 meses, 5=1+ ano)
- **Count**: how many job rejections were due to this skill
- **Estimate**: AI-estimated time to learn

---

### Test Easy Apply

Test the form-filling pipeline on a single job without going through the evaluation flow. Useful for debugging form fields and validating that Q&A works correctly.

```bash
# Test apply — fills everything but does NOT submit
uv run main.py test-apply "https://www.linkedin.com/jobs/view/1234567890" --no-submit

# Test with custom resume
uv run main.py test-apply "https://www.linkedin.com/jobs/view/1234567890" --resume "resume.pdf"
```

The browser stays open for inspection. Press Enter to close it. No evaluation is performed — the form is always filled regardless of fit.

---

### Search URL builder internals

When you pass `--keywords` instead of `--url`, JobPilot builds the appropriate search URL internally:

| CLI flag | LinkedIn param | Indeed param |
|----------|---------------|-------------|
| `--keywords "python"` | `keywords=python` | `q=python` |
| `--date-posted 24h` | `f_TPR=r86400` | `fromage=1` |
| `--date-posted week` | `f_TPR=r604800` | `fromage=7` |
| `--date-posted month` | `f_TPR=r2592000` | — |
| `--workplace remote` | `f_WT=2` | — |
| `--location Brasil` | `location=Brasil` | `l=Brasil` |
| `--site linkedin` | `linkedin.com/jobs/search/` | `br.indeed.com/jobs` |
| *(always)* | `f_AL=true` (Easy Apply) | `sc=0kf:attr(DSK7o)jt(fc)` |

For Glassdoor, use `--url` directly (URL structure is complex and not yet supported by the builder). For Indeed, only `--keywords`, `--date-posted`, and `--location` are supported.

---

## Windows Scheduled Tasks

Automate apply, connect, and report to run on every login — no terminal window visible.

### Setup

1. Edit the `.bat` files in `local/` with your search parameters and resume path.
2. Import each XML task into Windows Task Scheduler:

```powershell
# Run once as admin per task
schtasks /create /xml ".local\jobpilot_task.xml" /tn "JobPilot\Apply"
schtasks /create /xml ".local\jobpilot_connect_task.xml" /tn "JobPilot\Connect"
schtasks /create /xml ".local\jobpilot_report_task.xml" /tn "JobPilot\Report"
```

### How it works

| File | Purpose | Trigger |
|------|---------|---------|
| `.local/startup_apply.bat` | Searches and applies to jobs every login | Logon |
| `.local/startup_connect.bat` | Sends connection requests (scheduled mode) | Logon |
| `.local/startup_report.bat` | Sends monthly Telegram report | Logon |
| `.local/run_hidden.ps1` | PowerShell wrapper that hides the terminal | Called by XML tasks |
| `.local/*.xml` | Task Scheduler definitions — import once | — |

The `--scheduled` flag on connect/report ensures they only run once per day/month.
The `--headless` flag keeps Chrome invisible. `run_hidden.ps1` hides the terminal via `Start-Process -WindowStyle Hidden`.

---

## How the apply flow works

```
For each job found:
  1. Quick reject by title seniority (no AI token spent)
  2. Check if already applied or rejected (applied_jobs.json / rejected_jobs.json)
  3. AI evaluates (single Haiku call):
     - Job language (pt-BR only by default)
     - Seniority level match (if --level provided)
     - Technical fit with resume
     - Alignment with preferences
     - Estimates salary expectation
  4. If approved:
     - Click apply button
     - Fill form fields:
         - Salary filled directly from AI evaluation
         - Other questions checked against files/form_answers.json first (no AI if cached)
         - Remaining unknown questions sent to AI in a single batch call
         - All answers saved back to files/form_answers.json for future reuse
     - Submit
     - Save to applied_jobs.json
```

## Local files generated

| File | Description |
|------|-------------|
| `applied_jobs.json` | Record of all submitted applications |
| `rejected_jobs.json` | Record of all rejected jobs (skipped by AI or quick reject) |
| `files/last_urls.json` | Saved search params, URL, and page per task (`connect`, `apply_linkedin`, `apply_indeed`, `apply_glassdoor`) |
| `files/form_answers.json` | Cached form Q&A — edit manually to correct or pre-fill answers |
| `files/skills_gap.json` | Missing skills tracked across job evaluations (view with `skills list`) |
| `files/monthly_reports/` | Monthly report JSONs (`YYYY-MM.json`) |
| `screenshots.png` | Screenshot taken at the end of execution |
| `bot_profile/` | Chrome user data directory (persisted login session) |
| `logs/` | Application logs |

> These files are in `.gitignore` and are not committed to the repository.

## Project structure

```
jobpilot/
├── main.py                                   # Entry point and Typer CLI
├── local/                                    # Windows scheduled tasks
│   ├── startup_apply.bat                     # Daily apply on login
│   ├── startup_connect.bat                   # Daily connect on login
│   ├── startup_report.bat                    # Monthly report on login
│   ├── run_hidden.ps1                        # PowerShell wrapper (hidden terminal)
│   ├── run_hidden.vbs                        # Legacy VBS wrapper (still works)
│   └── *.xml                                 # Task Scheduler import files
├── scripts/
│   └── generate_resume.py                    # Generate PDF resume
└── src/
    ├── automation/
    │   ├── url_builder.py                    # URL builder from CLI flags
    │   ├── pages/                            # Site-specific page objects
    │   │   ├── jobs_search_page.py           # LinkedIn jobs search
    │   │   ├── people_search_page.py         # LinkedIn people search
    │   │   ├── glassdoor_jobs_page.py        # Glassdoor jobs search
    │   │   └── indeed_jobs_page.py           # Indeed jobs search
    │   └── tasks/                            # Orchestration layer
    │       ├── job_application_manager.py
    │       └── connection_manager.py
    ├── bot/
    │   └── telegram_bot.py                   # Telegram bot (polling + command handling)
    ├── core/
    │   ├── ai/
    │   │   └── llm_provider.py               # LLM abstraction (Claude / Ollama)
    │   └── use_cases/                        # Site-agnostic business logic
    │       ├── job_evaluator.py              # AI job evaluation
    │       ├── job_application_handler.py    # LinkedIn/Glassdoor Easy Apply forms
    │       ├── indeed_application_handler.py # Indeed apply forms
    │       ├── applied_jobs_tracker.py       # Deduplication persistence
    │       ├── salary_estimator.py           # AI salary estimation
    │       ├── skills_tracker.py             # Missing skills tracking
    │       ├── invitation_handler.py         # LinkedIn connection invites
    │       └── monthly_report.py             # Monthly statistics and reports
    └── utils/
        └── telegram.py                       # Telegram notification helper
```

### Adding a new job board

1. Create a new page object under `src/automation/pages/` implementing the same interface as `JobsSearchPage`
2. Instantiate it in `JobApplicationManager` based on the URL domain
3. The core use cases (`JobEvaluator`, `SalaryEstimator`, etc.) work unchanged
