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

## `engage`

Engaja no feed do LinkedIn (like + comentário + share via LLM).

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--min-post` | int | 1 | Piso do range de posts |
| `--max-post` | int | 20 | Teto do range de posts |
| `--posts-number` | str | `random` | `random` sorteia em [min,max]; ou inteiro exato (validado no range) |
| `--no-like` / `--no-comment` / `--no-share` | flag | false | Desativa cada ação |
| `--target` | list | — | Engaja só posts de empresa/pessoa-alvo (repetível) |
| `--save-targets` | flag | false | Persiste os `--target` (reuso futuro) |
| `--resume` | path | auto | Override do currículo |
| `--dry-run` | flag | false | Loga decisões/comentários sem agir |
| `--scheduled` | flag | false | Pula se já rodou hoje |
| `--force` | flag | false | Ignora skip-today |

```bash
# Engage: sorteia entre 1 e 20 posts (default)
uv run main.py engage

# Engage: exatamente 5 posts
uv run main.py engage --posts-number 5

# Engage: sorteia entre 3 e 8
uv run main.py engage --min-post 3 --max-post 8

# Engage com alvo (empresas relevantes) e salvar a lista
uv run main.py engage --target "Nubank" --target "Stone" --save-targets
```

O comentário tem A/B test embutido (variantes `insight`/`pergunta`); a
variante usada é gravada e aparece no relatório semanal. Para aprovação
humana antes de postar, use `/engage` no bot (human-in-loop).

---

## `autopost`

Gera post autoral via LLM com aprovação no Telegram. Ver `docs/specs/autopost-feature.md`.

```bash
uv run main.py autopost                          # weekday default
uv run main.py autopost --source manual --topic "..." --dry-run
uv run main.py autopost --no-telegram            # printa stdout
```

---

## `followup`

Follow-up DM pós-conexão: lê conexões novas, gera um DM curto via LLM e manda
pro Telegram pra aprovar. O envio acontece no bot ao aprovar.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--max-dms` | int | 5 | Máx DMs por run |
| `--resume` | path | auto | Override do currículo |
| `--scheduled` / `--force` | flag | false | Skip-today / ignora skip |

```bash
uv run main.py followup --max-dms 3
```

---

## `hired`

Benchmark de skills de quem foi **contratado recentemente** p/ um cargo-alvo, p/
ajustar teu perfil. Descobre posts de anúncio ("comecei como"/"started a new
position", ordenados por data → recência = data do post), abre cada perfil p/ as
competências (extraídas via LLM, filtrando ruído), deduplica por perfil (janela
de 6 meses) e agrega skill→contagem. Opcionalmente cruza com teu currículo (gap)
e mostra tendência mês a mês.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--role` / `-r` | str | (obrigatório) | Cargo-alvo (ex: "Software Engineer") |
| `--days` | int | 90 | Janela de recência da contratação (dias) |
| `--max-profiles` / `-n` | int | 10 | Máx. perfis a abrir/coletar |
| `--gap` | flag | false | Compara skills em alta com teu currículo (lacunas) |
| `--resume` | path | auto | Currículo p/ o gap |
| `--trend` | flag | false | Tendência das skills (subindo/caindo mês a mês; precisa ≥2 meses de coletas) |
| `--telegram` | flag | false | Envia o relatório completo (agregado + gap + tendência) via Telegram |
| `--out` | path | — | Exporta perfis coletados p/ CSV |
| `--dry-run` | flag | false | Só descobre/loga anúncios; não abre perfis |

Dados em `.local/files/hired_profiles.json` (dedup por `profile_url`, TTL no agregado).

```bash
uv run main.py hired --role "Desenvolvedor de Software Pleno" --gap --trend --telegram
```

> Modelo de extração: usa o `eval` provider. Pra forçar Claude só numa run sem mexer no
> `.env`: `LLM_PROVIDER_EVAL=claude uv run main.py hired --role ...`.

---

## `dashboard`

Dashboard TUI ao vivo (textual): candidaturas, engagement, autopost, SSI e
progresso de metas. `r` atualiza, `q` sai.

```bash
uv run main.py dashboard
```

---

## `export`

Exporta vagas para CSV (Excel/Sheets/Notion importam direto).

```bash
uv run main.py export applied                    # .local/export_applied.csv
uv run main.py export rejected -o rej.csv
uv run main.py export all
```

---

## `searches`

Saved-searches em rodízio (mais cobertura sem repetir a mesma busca).

```bash
uv run main.py searches add "tech-recruiters" "https://.../search/..." --task connect
uv run main.py searches list
uv run main.py searches next --task connect      # avança o cursor
uv run main.py searches remove 0
```

Use no rodízio: `uv run main.py connect --rotate --scheduled`.

---

## `goals`

Metas semanais; o relatório semanal avisa o que está atrás.

```bash
uv run main.py goals show
uv run main.py goals set applications 12
uv run main.py goals set connections 60
```

Métricas suportadas: `applications`, `connections`, `posts`, `comments`.

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
- `/engage [n]` — Engage feed com aprovação humana (human-in-loop)
- `/autopost`, `/autopost_topic`, `/autopost_format`, `/autopost_list` — posts autorais
- `/followup [n]` — DMs pós-conexão para aprovar
- `/status` — Check running task
- `/stop` — Stop current task
- `/resume` — Upload new resume
- `/ping` — Bot liveness check
- `/reiniciar` — Restart bot process
- `/help` — List all commands

Botões de aprovação (inline): autopost (✅/❌/✏️/🔄), follow-up DM (✅/❌/✏️/🔄)
e engage (✅ Postar / ❌ Pular / ✏️ Editar).

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

Manage cached form answers (`files/form_answers.json`).

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
