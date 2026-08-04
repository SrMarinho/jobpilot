# Windows Scheduled Tasks

Automate JobPilot to run on every Windows login — no terminal visible, Chrome headless.

## Task overview

Six scheduled tasks, all triggered at user logon:

| Task | Script | What it does |
|------|--------|-------------|
| `JobPilot Apply` | `.local/startup_apply.bat` | Busca vagas e candidata (`jobs apply`) |
| `JobPilot Connect` | `.local/startup_connect.ps1` | Envia convites de conexão (`network connect --scheduled`) |
| `JobPilot Engage` | `.local/startup_engage.ps1` | Engaja no feed + captura métricas do perfil (`content engage`, `profile capture`) |
| `JobPilot Autopost` | `.local/startup_autopost.ps1` | Gera post autoral do dia (`content autopost --daily`) |
| `JobPilot Report` | `.local/startup_report.bat` | Relatório mensal via Telegram (`insights report --scheduled`) |
| `JobPilot Hired` | `.local/startup_hired.ps1` | Benchmark de skills de contratados + gap/trend (`jobs hired`). **Roda por último** (logon + delay de 1h) |

Há ainda `.local/startup_drain.bat`, que não é tarefa agendada: dreno manual das
aprovações do Telegram (`content autopost --drain`), sem browser.

> **Ordem "por último":** a task `Hired` usa `LogonTrigger` com `<Delay>PT1H</Delay>`, então
> dispara 1h após o logon — depois das demais. Mesmo que coincidam, o *browser lock* serializa
> (uma sessão Chrome por vez; quem chega depois aguarda na fila — ver
> [Browser lock](browser-lock.md)).
>
> **Provider:** `startup_hired.ps1` seta `LLM_PROVIDER_EVAL=claude` **apenas no escopo do processo**
> (extração de skills melhor que o ollama local). Não altera o `.env` global.

## How hiding works

```
Task Scheduler (LogonTrigger)
  → powershell.exe -WindowStyle Hidden
    → run_hidden.ps1
      → Start-Process cmd.exe -WindowStyle Hidden
        → startup_*.bat / startup_*.ps1
          → uv run main.py --headless <grupo> <comando>
```

Two layers of hiding:
1. **PowerShell wrapper** (`run_hidden.ps1`): `Start-Process -WindowStyle Hidden` — hides cmd.exe window
2. **`--headless` flag**: Chrome runs without visible window

> ⚠️ `--headless` é flag **global**, então vem antes do grupo:
> `main.py --headless jobs apply`, não `main.py jobs apply --headless`.

## Setup

### 1. Edit the scripts

Os scripts em `.local/` trazem caminhos absolutos da máquina original — ajuste o
caminho do `uv` e do repositório antes de usar.

**`.local/startup_apply.bat`:**
```bat
"C:\Users\...\.local\bin\uv" run main.py --headless jobs apply ^
  --keywords "desenvolvedor backend" ^
  --site linkedin ^
  --date-posted 24h ^
  --resume "resume.pdf" ^
  --level junior --level pleno ^
  --max-pages 2 ^
  --no-save
```

**`.local/startup_connect.ps1`:**
```powershell
& 'C:\Users\...\.local\bin\uv' run main.py --headless network connect --url $Url --scheduled
```

### 2. Import into Task Scheduler

Run **as Administrator** (schtasks requires elevation). O helper
`.local/reimport_tasks.ps1` apaga e recria as tarefas:

```powershell
# PowerShell elevado, na raiz do repo:
.\.local\reimport_tasks.ps1
```

Ou manualmente:

```powershell
# Delete existing (if re-importing)
schtasks /delete /tn "JobPilot Apply" /f
schtasks /delete /tn "JobPilot Connect" /f
schtasks /delete /tn "JobPilot Report" /f
schtasks /delete /tn "JobPilot Hired" /f

# Import
schtasks /create /xml ".local\jobpilot_task.xml" /tn "JobPilot Apply"
schtasks /create /xml ".local\jobpilot_connect_task.xml" /tn "JobPilot Connect"
schtasks /create /xml ".local\jobpilot_engage_task.xml" /tn "JobPilot Engage"
schtasks /create /xml ".local\jobpilot_autopost_task.xml" /tn "JobPilot Autopost"
schtasks /create /xml ".local\jobpilot_report_task.xml" /tn "JobPilot Report"
schtasks /create /xml ".local\jobpilot_hired_task.xml" /tn "JobPilot Hired"
```

> `reimport_tasks.ps1` cobre só Apply/Connect/Report/Hired — Engage e Autopost
> precisam do `schtasks /create` manual acima.

### 3. Verify

Open `taskschd.msc`, check under `JobPilot` folder. Right-click each task → Run to test manually.

## Task configuration details

| Setting | Apply | Connect | Engage | Autopost | Report | Hired |
|---------|-------|---------|--------|----------|--------|-------|
| Trigger | Logon | Logon | Logon | Logon | Logon | Logon + 1h delay |
| Time limit | 4 hours | 2 hours | 2 hours | 1 hour | 1 hour | 1 hour |
| Multiple instances | Ignore | Ignore | Ignore | Ignore | Ignore | Ignore |
| Battery | Always run | Always run | Always run | Always run | Always run | Always run |
| Hidden | Yes (PowerShell) | Yes | Yes | Yes | Yes | Yes |

## Scheduled mode flags

| Flag | Effect |
|------|--------|
| `--scheduled` (connect) | Skip if already ran today. Skip if weekly invite limit reached. |
| `--scheduled` (engage) | Skip if already ran today. |
| `--scheduled` (report) | Send via Telegram only once per month. Skips if already sent this month. |
| `--daily` (autopost) | Gera no máximo um post por dia. |
| `--headless` (global) | Chrome runs without visible window |
| `--no-save` (apply) | Don't overwrite manually saved search config |
| `--max-pages 2` (apply) | Limit to 2 pages per run (prevents endless runs on startup) |

## Troubleshooting

**"No such command":**
O CLI é agrupado (`jobs`, `network`, `content`, `profile`, `insights`, `config`).
Comandos antigos de nível raiz (`main.py apply`, `main.py hired`) não existem mais —
ver [CLI Reference](cli.md).

**Task doesn't run:**
Check Task Scheduler history (enable in Event Viewer). Common issues: task disabled, password changed, battery settings blocking.

**Terminal still visible:**
Ensure the XML task uses `powershell.exe` (not `cmd.exe` directly). Verify `run_hidden.ps1` exists and has the `-WindowStyle Hidden` parameter. Try running the `.bat` directly to isolate the issue.

**Chrome visible:**
Verify `--headless` is in the batch file. Check `HEADLESS` env var isn't set to `FALSE` (overrides CLI flag).

**Application errors:**
Check `logs/` directory. Common causes: expired login session (re-run `login linkedin`), Ollama not running, resume file not found, `USER_NAME`/`USER_HEADLINE` ausentes no `.env` (obrigatórios para os comandos de conteúdo).

**Conta em checkpoint:**
Se o LinkedIn pedir verificação, a automação para de propósito e manda alerta no
Telegram. Abra o Chrome e resolva manualmente antes do próximo run.
