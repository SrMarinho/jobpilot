# Windows Scheduled Tasks

Automate JobPilot to run on every Windows login — no terminal visible, Chrome headless.

## Task overview

Three scheduled tasks, all triggered at user logon:

| Task | Batch file | What it does |
|------|-----------|-------------|
| `JobPilot\Apply` | `local/startup_apply.bat` | Searches jobs and applies (daily) |
| `JobPilot\Connect` | `local/startup_connect.bat` | Sends connection requests (daily, respects limits) |
| `JobPilot\Report` | `local/startup_report.bat` | Sends monthly report via Telegram |

## How hiding works

```
Task Scheduler (LogonTrigger)
  → powershell.exe -WindowStyle Hidden
    → run_hidden.ps1
      → Start-Process cmd.exe -WindowStyle Hidden
        → startup_*.bat
          → uv run main.py ... --headless
```

Two layers of hiding:
1. **PowerShell wrapper** (`run_hidden.ps1`): `Start-Process -WindowStyle Hidden` — hides cmd.exe window
2. **`--headless` flag**: Chrome runs without visible window

## Setup

### 1. Edit the batch files

Edit the search parameters and resume path in each `.bat`:

**`local/startup_apply.bat`:**
```bat
"C:\Users\...\.local\bin\uv" run main.py apply ^
  --keywords "desenvolvedor backend" ^
  --site linkedin ^
  --date-posted 24h ^
  --resume "resume.pdf" ^
  --level junior --level pleno ^
  --max-pages 2 ^
  --llm-provider langchain ^
  --eval-provider langchain ^
  --headless ^
  --no-save
```

**`local/startup_connect.bat`:**
```bat
"C:\Users\...\.local\bin\uv" run main.py connect ^
  --keywords "tech recruiter" ^
  --network S ^
  --scheduled ^
  --headless
```

### 2. Import into Task Scheduler

```powershell
# Delete existing (if re-importing)
schtasks /delete /tn "JobPilot\Apply" /f
schtasks /delete /tn "JobPilot\Connect" /f
schtasks /delete /tn "JobPilot\Report" /f

# Import
schtasks /create /xml "local\jobpilot_task.xml" /tn "JobPilot\Apply"
schtasks /create /xml "local\jobpilot_connect_task.xml" /tn "JobPilot\Connect"
schtasks /create /xml "local\jobpilot_report_task.xml" /tn "JobPilot\Report"
```

### 3. Verify

Open `taskschd.msc`, check under `JobPilot` folder. Right-click each task → Run to test manually.

## Task configuration details

| Setting | Apply | Connect | Report |
|---------|-------|---------|--------|
| Trigger | Logon | Logon | Logon |
| Time limit | 4 hours | 2 hours | 1 hour |
| Multiple instances | Ignore | Ignore | Ignore |
| Battery | Always run | Always run | Always run |
| Hidden | Yes (PowerShell) | Yes | Yes |

## Scheduled mode flags

| Flag | Effect |
|------|--------|
| `--scheduled` (connect) | Skip if already ran today. Skip if weekly invite limit reached. |
| `--scheduled` (report) | Send via Telegram only once per month. Skips if already sent this month. |
| `--headless` | Chrome runs without visible window |
| `--no-save` (apply) | Don't overwrite manually saved search config |
| `--max-pages 2` (apply) | Limit to 2 pages per run (prevents endless runs on startup) |

## Troubleshooting

**Task doesn't run:**
Check Task Scheduler history (enable in Event Viewer). Common issues: task disabled, password changed, battery settings blocking.

**Terminal still visible:**
Ensure the XML task uses `powershell.exe` (not `cmd.exe` directly). Verify `run_hidden.ps1` exists and has the `-WindowStyle Hidden` parameter. Try running the `.bat` directly to isolate the issue.

**Chrome visible:**
Verify `--headless` is in the batch file. Check `HEADLESS` env var isn't set to `FALSE` (overrides CLI flag).

**Application errors:**
Check `logs/` directory. Common causes: expired login session (re-run `login linkedin`), Ollama not running, resume file not found.
