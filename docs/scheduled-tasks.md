# Windows Scheduled Tasks

Automate JobPilot to run on every Windows login — no terminal visible, Chrome headless.

## Task overview

Duas tarefas agendadas. Tudo que usa browser roda numa **cadeia única e
sequencial**, a `JobPilot Daily` (`.local/startup_daily.ps1`, 1×/dia no logon ou às 08h,
`jobpilot_daily_task.xml`). Cada etapa só começa quando a anterior termina:

| # | Etapa | Script | Dias | What it does |
|---|-------|--------|------|-------------|
| 1 | report | `.local/startup_report.bat` | segunda | Relatório mensal via Telegram (`insights report --scheduled`) |
| 2 | autopost | `.local/startup_autopost.ps1` | ter/sex | Gera post autoral do dia (`content autopost --daily`) |
| 3 | connect | `.local/startup_connect.ps1` | todo dia | Envia convites de conexão (`network connect --scheduled`) |
| 4 | apply | `.local/startup_apply.bat` | todo dia | Busca vagas e candidata (`jobs apply`) |
| 5 | engage | `.local/startup_engage.ps1` | todo dia | Engaja no feed + captura métricas do perfil (`content engage`, `profile capture`) |
| 6 | hired | `.local/startup_hired.ps1` | sábado | Benchmark de skills de contratados + gap/trend (`jobs hired`) |

Falha numa etapa não interrompe as seguintes; o exit final é 1 se alguma falhou.
Cada etapa chama o `startup_*` próprio, então o env de provider de cada uma
continua isolado.

> **Por que cadeia e não uma tarefa por comando:** eram seis tarefas com
> horário próprio e `StartWhenAvailable`. Com o PC desligado no horário, o
> Agendador disparava todas as perdidas no mesmo segundo do boot; o apply
> segurava o browser lock e o engage estourava a espera e morria na fila.

Há ainda a task `JobPilot Drain` (`.local/startup_drain.bat`,
`jobpilot_drain_task.xml`), que roda **de hora em hora** e é a única sem
browser. Faz três coisas, nessa ordem:

1. dreno das aprovações do Telegram (`content autopost --drain`);
2. um job da fila de autoevolução (`config evolve drain`);
3. varredura de log 1×/dia (`config evolve scan --once-a-day`).

⚠️ O `ExecutionTimeLimit` dessa task é **`PT30M`**, não `PT10M`: o patch da
autoevolução leva minutos entre LLM, ruff, pytest e smoke, e com dez minutos o
Agendador cortava no meio deixando worktree órfão. Reimportar um XML antigo
reintroduz o problema. Ver [Autoevolução](evolution.md).

Os itens 2 e 3 são inertes sem `EVOLVE_ENABLED=true` no `.env`.

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

O script também apaga as tarefas avulsas antigas (`JobPilot Apply`, `Connect`,
`Report`, `Autopost`, `Hired`, `Engage`), que viraram etapas da `Daily`.

Ou manualmente:

```powershell
schtasks /create /xml ".local\jobpilot_daily_task.xml" /tn "JobPilot Daily"
schtasks /create /xml ".local\jobpilot_drain_task.xml" /tn "JobPilot Drain"
```

### 3. Verify

Open `taskschd.msc`, check under `JobPilot` folder. Right-click each task → Run to test manually.

## Task configuration details

| Setting | Daily | Drain |
|---------|-------|-------|
| Trigger | Logon (+2 min) e diário 08h (+ até 30 min); roda 1×/dia | De hora em hora |
| Time limit | 10 hours (soma das etapas; apply sozinho chega a ~4h) | 30 min |
| Missed run | `StartWhenAvailable`: roda no boot se o PC estava desligado | idem |
| Multiple instances | Ignore | Ignore |
| Battery | Always run | Always run |
| Hidden | Yes (`run_hidden.vbs`) | Yes |

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
