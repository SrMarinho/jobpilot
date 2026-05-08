# JobPilot CLI Reference

All commands, flags, and usage examples for the JobPilot CLI.

## Global options

| Flag | Description |
|------|-------------|
| `--headless` | Force headless Chrome (overrides `HEADLESS` env var) |
| `--help` | Show command help |
| `--install-completion` | Install shell completion (bash/zsh/fish/powershell) |

---

## `login` / `logout`

```
login <SITE>     Open browser to log in (linkedin, glassdoor, indeed)
logout <SITE>    Clear saved session
```

Session persists in `bot_profile/` directory.

---

## `apply`

Apply to jobs via Easy Apply on LinkedIn, Glassdoor, or Indeed.

### Search builder flags (new)

```bash
uv run main.py apply --keywords "python backend" --site linkedin --workplace remote --date-posted 24h
```

### Raw URL fallback

```bash
uv run main.py apply --url "https://www.linkedin.com/jobs/search/?keywords=python&f_AL=true"
```

### Resume from interruption

```bash
uv run main.py apply --continue              # last site
uv run main.py apply --continue --site indeed
```

### Complete flag reference

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--keywords` `-k` | string | — | Search terms |
| `--url` `-u` | string | — | Full search URL (overrides keywords) |
| `--site` | string | last used | Target: `linkedin`, `glassdoor`, `indeed` |
| `--date-posted` | enum | — | `24h`, `week`, `month`, `any` |
| `--workplace` | enum | — | `on-site`, `remote`, `hybrid` |
| `--location` | string | — | Location filter |
| `--experience` | enum | — | `internship`, `entry`, `associate`, `mid-senior`, `director`, `executive` |
| `--resume` `-r` | path | resume.txt | Resume PDF or TXT |
| `--preferences` `-p` | string | "" | Preferences for AI evaluation |
| `--level` `-l` | list | [] | Seniority filter: `--level junior --level pleno` |
| `--start-page` | int | 1 | Page to start from |
| `--max-pages` | int | 100 | Max pages to process |
| `--max-applications` | int | 0 | Stop after N applications (0=unlimited) |
| `--continue` | flag | false | Resume from last saved page |
| `--no-save` | flag | false | Don't overwrite saved config |
| `--no-submit` | flag | false | Fill forms but don't submit |
| `--llm-provider` | string | from .env | Override: `claude` or `langchain` |
| `--llm-model` | string | from .env | Override LLM model |
| `--eval-provider` | string | from .env | Override eval AI |
| `--eval-model` | string | from .env | Override eval model |

### Examples

```bash
# LinkedIn: Python backend, remote, last 24h
uv run main.py apply \
  --keywords "python backend" --site linkedin \
  --workplace remote --date-posted 24h \
  --level junior --level pleno \
  --resume "resume.pdf"

# Indeed: same search
uv run main.py apply \
  --keywords "python backend" --site indeed \
  --date-posted week

# Raw URL (Glassdoor)
uv run main.py apply --url "https://www.glassdoor.com/Job/..."

# Dry run (no submit)
uv run main.py apply --keywords "python" --site linkedin --no-submit

# Stop after 5 applications
uv run main.py apply --keywords "python" --site linkedin --max-applications 5
```

---

## `connect`

Send LinkedIn connection requests.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--keywords` `-k` | string | — | Search terms |
| `--url` `-u` | string | — | Full URL (overrides keywords) |
| `--network` | enum | — | `F`=1st, `S`=2nd, `O`=3rd+ |
| `--start-page` | int | 1 | Page to start |
| `--max-pages` | int | 100 | Max pages |
| `--continue` | flag | false | Resume from last page |
| `--scheduled` | flag | false | Skip if already ran today or weekly limit |

```bash
# Search builders
uv run main.py connect --keywords "tech recruiter" --network S
uv run main.py connect --keywords "python developer" --network F

# Scheduled mode (run once per day)
uv run main.py connect --scheduled --headless

# Resume
uv run main.py connect --continue
```

---

## `test-apply`

Test Easy Apply form filling on a single job (skips AI evaluation).

```bash
uv run main.py test-apply "https://www.linkedin.com/jobs/view/1234567890"
uv run main.py test-apply "JOB_URL" --no-submit    # fill only, don't send
uv run main.py test-apply "JOB_URL" --resume "resume.pdf"
```

---

## `bot`

Start Telegram bot for remote control.

```bash
uv run main.py bot
uv run main.py bot --resume "resume.pdf"
```

Telegram commands:
- `/apply <url>` — Start applying
- `/connect` — Start connection requests
- `/status` — Check running task
- `/stop` — Stop current task
- `/resume` — Upload new resume
- `/ping` — Bot liveness check
- `/reiniciar` — Restart bot process
- `/help` — List all commands

---

## `provider`

Switch LLM backends without editing `.env` manually.

```bash
# Show current config
uv run main.py provider show

# Set evaluation AI
uv run main.py provider set eval claude
uv run main.py provider set eval langchain --model llama3.1:8b

# Set form Q&A AI
uv run main.py provider set llm claude
uv run main.py provider set llm langchain --model deepseek-r1:14b
```

| Target | Description |
|--------|-------------|
| `eval` | AI for job evaluation (match/fit analysis) |
| `llm` | AI for form Q&A (answering unknown questions) |

---

## `answers`

Manage cached form answers (`files/qa.json`).

```bash
uv run main.py answers list          # Show unanswered questions
uv run main.py answers show          # Show all cached Q&A
uv run main.py answers set 5 "3"     # Set answer #5 to "3"
uv run main.py answers fill          # Interactive fill mode
uv run main.py answers clear         # Delete all cached answers
```

---

## `skills`

View missing skills detected from job rejections.

```bash
uv run main.py skills list                   # All skills by frequency
uv run main.py skills list --category python # Filter by category
uv run main.py skills list --level 3         # Filter by learning difficulty
uv run main.py skills top --n 15             # Top N most demanded
uv run main.py skills clear                  # Reset tracking
```

---

## `report`

Generate monthly statistics.

```bash
uv run main.py report                  # Current month
uv run main.py report --prev           # Previous month
uv run main.py report --month 2026-03  # Specific month
uv run main.py report --year 2026      # Annual summary
uv run main.py report --telegram       # Send via Telegram
uv run main.py report --scheduled      # Telegram once per month
```
