# JobPilot

Automated job application bot with AI-powered evaluation. Currently supports LinkedIn (Easy Apply + connection requests), with an architecture designed to add new job boards.

## Features

- **Apply**: Evaluates jobs against your resume and applies automatically
  - Filters by language (pt-BR only by default)
  - Filters by seniority level
  - Estimates salary expectation based on job and market data
  - Answers custom form questions using AI
  - Tracks applied jobs to avoid duplicates
- **Connect**: Sends connection requests automatically (LinkedIn)
- **Bot**: Control JobPilot remotely via Telegram — start/stop tasks, check status, and receive notifications for every application sent
- **Provider**: Switch AI backends at runtime without editing `.env` manually

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
uv run main.py login linkedin
```

A browser window will open. Log in normally, then close it. The session is persisted in `bot_profile/` and reused on every subsequent run.

## Usage

> **Tip:** The first time you run `connect` or `apply`, you must pass `--url`. After that, the URL is saved locally in `files/last_urls.json` and you can omit it in future runs.

---

### Apply to jobs

```bash
# First run — URL required
uv run main.py apply --url "JOB_SEARCH_URL" --resume "path/to/resume.pdf"

# Subsequent runs — reuses last saved URL and parameters
uv run main.py apply

# Resume from the last page where it stopped
uv run main.py apply --continue

# Resume a specific site's saved config
uv run main.py apply --continue --site glassdoor
```

All parameters are saved per site (`apply_linkedin`, `apply_glassdoor`, `apply_indeed`) and restored automatically on the next run.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--url` | First run only | Job search URL (LinkedIn: enable Easy Apply filter with `f_AL=true`) |
| `--resume` | No | Path to resume PDF or TXT (default: `resume.txt`) |
| `--preferences` | No | Preferences to guide evaluation (e.g. `'prefer backend, Python, remote'`) |
| `--level` | No | Seniority level filter (multiple allowed): `junior`, `pleno`, `senior` |
| `--max-pages` | No | Max pages to process (default: 100) |
| `--max-applications` | No | Stop after N applications (default: unlimited) |
| `--no-save` | No | Run without overwriting the saved URL/config for this site |
| `--site` | No | Resume saved config for a specific site: `linkedin`, `glassdoor`, `indeed` |
| `--eval-provider` | No | Override eval AI for this run only: `claude` or `langchain` |
| `--eval-model` | No | Override eval model for this run only |
| `--llm-provider` | No | Override form Q&A AI for this run only: `claude` or `langchain` |
| `--llm-model` | No | Override form Q&A model for this run only |

**Example (LinkedIn):**
```bash
uv run main.py apply \
  --url "https://www.linkedin.com/jobs/search/?keywords=python+developer&f_AL=true" \
  --resume "resume.pdf" \
  --preferences "Python ou Node.js backend, remoto, apenas vagas em português" \
  --level junior pleno \
  --eval-provider langchain
```

---

### Send connection requests (LinkedIn)

```bash
# First run — URL required
uv run main.py connect --url "PEOPLE_SEARCH_URL"

# Subsequent runs — reuses last saved URL
uv run main.py connect

# Resume from the last page where it stopped
uv run main.py connect --continue
```

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--url` | First run only | LinkedIn people search URL |
| `--start-page` | No | Page to start from (default: 1) |
| `--max-pages` | No | Max pages to process (default: 100) |
| `--continue` | No | Resume from the last page where the previous run stopped |

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

JobPilot caches answers to form questions in `files/qa.json` so it doesn't need to call the AI repeatedly. Use the `answers` command to inspect and edit this cache:

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

Generates and sends a summary of the previous month via Telegram:

```bash
# Send report now (always sends — manual use)
uv run main.py report

# Send report for a specific month
uv run main.py report --month 2025-03

# Scheduled mode: sends only once per month, skips if already sent
uv run main.py report --scheduled
```

The report includes: applications sent, connections made, rejection breakdown by reason, match rate, average estimated salary, top skills that blocked jobs this month, and evolution vs the previous month (↑/↓).

Reports are saved to `files/monthly_reports/YYYY-MM.json` for historical reference.

> To automate: create a Windows Task Scheduler task pointing to `local/startup_report.bat` with an **At startup** trigger. The `--scheduled` flag ensures it only sends once per month regardless of how many times the PC boots.

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
         - Other questions checked against files/qa.json first (no AI if cached)
         - Remaining unknown questions sent to AI in a single batch call
         - All answers saved back to files/qa.json for future reuse
     - Submit
     - Save to applied_jobs.json
```

## Local files generated

| File | Description |
|------|-------------|
| `applied_jobs.json` | Record of all submitted applications |
| `rejected_jobs.json` | Record of all rejected jobs (skipped by AI or quick reject) |
| `files/last_urls.json` | Last URL and page saved per task (`connect`, `apply`) |
| `files/qa.json` | Cached form Q&A — edit manually to correct or pre-fill answers |
| `screenshots.png` | Screenshot taken at the end of execution |

> These files are in `.gitignore` and are not committed to the repository.

## Project structure

```
jobpilot/
├── main.py                                   # Entry point and CLI
└── src/
    ├── automation/
    │   ├── pages/                            # Site-specific page objects
    │   │   ├── people_search_page.py         # LinkedIn people search
    │   │   └── jobs_search_page.py           # LinkedIn jobs search
    │   └── tasks/                            # Orchestration layer
    │       ├── connection_manager.py
    │       └── job_application_manager.py
    ├── bot/
    │   └── telegram_bot.py                   # Telegram bot (polling + command handling)
    ├── core/
    │   └── use_cases/                        # Site-agnostic business logic
    │       ├── job_evaluator.py              # AI job evaluation
    │       ├── salary_estimator.py           # AI salary estimation
    │       ├── job_application_handler.py    # Form filling and submission
    │       └── applied_jobs_tracker.py       # Persistence layer
    ├── core/
    │   ├── ai/
    │   │   └── llm_provider.py               # LLM provider abstraction (Claude / Ollama)
    │   └── use_cases/                        # Site-agnostic business logic
    │       ├── job_evaluator.py              # AI job evaluation
    │       ├── salary_estimator.py           # AI salary estimation
    │       ├── job_application_handler.py    # Form filling and submission
    │       └── applied_jobs_tracker.py       # Persistence layer
    └── utils/
        └── telegram.py                       # Telegram notification helper
```

### Adding a new job board

1. Create a new page object under `src/automation/pages/` implementing the same interface as `JobsSearchPage`
2. Instantiate it in `JobApplicationManager` based on the URL domain
3. The core use cases (`JobEvaluator`, `SalaryEstimator`, etc.) work unchanged
