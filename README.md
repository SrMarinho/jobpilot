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
```

> Set `HEADLESS=TRUE` to run Chrome in the background (no visible window).

## Usage

### Apply to jobs

```bash
uv run python main.py apply --url "JOB_SEARCH_URL" --resume "path/to/resume.pdf"
```

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--url` | Yes | Job search URL (LinkedIn: enable Easy Apply filter with `f_AL=true`) |
| `--resume` | No | Path to resume PDF or TXT (default: `resume.txt`) |
| `--preferences` | No | Preferences to guide evaluation (e.g. `'prefer backend, Python, remote'`) |
| `--level` | No | Seniority level: `junior`, `pleno`, `senior` |
| `--max-pages` | No | Max pages to process (default: 100) |

**Example (LinkedIn):**
```bash
uv run python main.py apply \
  --url "https://www.linkedin.com/jobs/search/?keywords=python+developer&f_AL=true" \
  --resume "resume.pdf" \
  --preferences "prefer backend, Python, remote" \
  --level junior
```

---

### Send connection requests (LinkedIn)

```bash
uv run python main.py connect --url "PEOPLE_SEARCH_URL"
```

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--url` | Yes | LinkedIn people search URL |
| `--start-page` | No | Page to start from (default: 1) |
| `--max-pages` | No | Max pages to process (default: 100) |

---

## How the apply flow works

```
For each job found:
  1. Check if already applied (applied_jobs.json)
  2. AI evaluates:
     - Job language (pt-BR only by default)
     - Seniority level match (if --level provided)
     - Technical fit with resume
     - Alignment with preferences
  3. If approved:
     - Estimate salary expectation
     - Click apply button
     - Fill form fields (salary, custom questions via AI)
     - Submit
     - Save to applied_jobs.json
```

## Local files generated

| File | Description |
|------|-------------|
| `applied_jobs.json` | Record of all submitted applications |
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
    └── core/
        └── use_cases/                        # Site-agnostic business logic
            ├── job_evaluator.py              # AI job evaluation
            ├── salary_estimator.py           # AI salary estimation
            ├── job_application_handler.py    # Form filling and submission
            └── applied_jobs_tracker.py       # Persistence layer
```

### Adding a new job board

1. Create a new page object under `src/automation/pages/` implementing the same interface as `JobsSearchPage`
2. Instantiate it in `JobApplicationManager` based on the URL domain
3. The core use cases (`JobEvaluator`, `SalaryEstimator`, etc.) work unchanged
