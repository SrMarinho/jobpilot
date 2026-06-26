# JobPilot CLI Reference

All commands, flags, and usage examples for the JobPilot CLI.

## Command structure

```
login / logout / bot          ← top-level utilities

jobs      apply / hired / export / test-apply / searches / skills / answers
network   connect / followup
content   engage / autopost
profile   capture / skills / views / ssi / appearances
insights  report / dashboard
config    provider (key) / db / goals / telegram-topics
```

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

## `jobs` — vagas e candidaturas

### `jobs apply`

Apply to jobs via Easy Apply on LinkedIn, Glassdoor, or Indeed.

```bash
uv run main.py jobs apply --keywords "python backend" --site linkedin --workplace remote --date-posted 24h
uv run main.py jobs apply --url "https://www.linkedin.com/jobs/search/?keywords=python&f_AL=true"
uv run main.py jobs apply --continue              # resume from last page
uv run main.py jobs apply --continue --site indeed
```

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

```bash
# LinkedIn: Python backend, remote, last 24h
uv run main.py jobs apply \
  --keywords "python backend" --site linkedin \
  --workplace remote --date-posted 24h \
  --level junior --level pleno \
  --resume "resume.pdf"

# Stop after 5 applications
uv run main.py jobs apply --keywords "python" --site linkedin --max-applications 5
```

---

### `jobs hired`

Benchmark de skills de quem foi **contratado recentemente** p/ um cargo-alvo.
Descobre posts de anúncio, abre perfis, extrai skills via LLM, agrega por frequência.
Opcionalmente cruza com teu currículo (gap) e mostra tendência mês a mês.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--role` / `-r` | str | (obrigatório) | Cargo-alvo (ex: "Software Engineer") |
| `--days` | int | 90 | Janela de recência da contratação (dias) |
| `--max-profiles` / `-n` | int | 10 | Máx. perfis a abrir/coletar |
| `--gap` | flag | false | Compara skills em alta com teu currículo |
| `--resume` | path | auto | Currículo p/ o gap |
| `--trend` | flag | false | Tendência das skills mês a mês (precisa ≥2 meses) |
| `--telegram` | flag | false | Envia relatório completo via Telegram |
| `--out` | path | — | Exporta perfis coletados p/ CSV |
| `--dry-run` | flag | false | Só descobre/loga anúncios; não abre perfis |

```bash
uv run main.py jobs hired --role "Desenvolvedor de Software Pleno" --gap --trend --telegram
```

> Modelo de extração: usa o `eval` provider. Para forçar Claude numa run:
> `LLM_PROVIDER_EVAL=claude uv run main.py jobs hired --role ...`

---

### `jobs export`

Exporta vagas para CSV (Excel/Sheets/Notion importam direto).

```bash
uv run main.py jobs export applied                    # .local/export_applied.csv
uv run main.py jobs export rejected -o rej.csv
uv run main.py jobs export all
```

---

### `jobs test-apply`

Test Easy Apply form filling on a single job (skips AI evaluation).

```bash
uv run main.py jobs test-apply "https://www.linkedin.com/jobs/view/1234567890"
uv run main.py jobs test-apply "JOB_URL" --no-submit    # fill only, don't send
uv run main.py jobs test-apply "JOB_URL" --resume "resume.pdf"
```

---

### `jobs searches`

Saved-searches em rodízio (mais cobertura sem repetir a mesma busca).

```bash
uv run main.py jobs searches add "tech-recruiters" "https://.../search/..." --task connect
uv run main.py jobs searches list
uv run main.py jobs searches next --task connect      # avança o cursor
uv run main.py jobs searches remove 0
```

Use no rodízio: `uv run main.py network connect --rotate --scheduled`.

---

### `jobs skills`

View missing skills detected from job rejections.

```bash
uv run main.py jobs skills list                   # All skills by frequency
uv run main.py jobs skills list --category python # Filter by category
uv run main.py jobs skills list --level 3         # Filter by learning difficulty
uv run main.py jobs skills top --n 15             # Top N most demanded
uv run main.py jobs skills clear                  # Reset tracking
```

---

### `jobs answers`

Manage cached form answers (`files/form_answers.json`).

```bash
uv run main.py jobs answers list          # Show unanswered questions
uv run main.py jobs answers show          # Show all cached Q&A
uv run main.py jobs answers set 5 "3"     # Set answer #5 to "3"
uv run main.py jobs answers fill          # Interactive fill mode
uv run main.py jobs answers clear         # Delete all cached answers
```

---

## `network` — networking LinkedIn

### `network connect`

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
| `--rotate` | flag | false | Use next saved-search in rotation |

```bash
uv run main.py network connect --keywords "tech recruiter" --network S
uv run main.py network connect --scheduled --headless
uv run main.py network connect --rotate --scheduled
```

---

### `network followup`

Follow-up DM pós-conexão: lê conexões novas, gera DM curto via LLM e manda
pro Telegram pra aprovar. O envio acontece no bot ao aprovar.

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--max-dms` | int | 5 | Máx DMs por run |
| `--resume` | path | auto | Override do currículo |
| `--scheduled` / `--force` | flag | false | Skip-today / ignora skip |

```bash
uv run main.py network followup --max-dms 3
```

---

## `content` — conteúdo LinkedIn

### `content engage`

Engaja no feed do LinkedIn (like + comentário + share via LLM).

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--min-post` | int | 1 | Piso do range de posts |
| `--max-post` | int | 20 | Teto do range de posts |
| `--posts-number` | str | `random` | `random` sorteia em [min,max]; ou inteiro exato |
| `--no-like` / `--no-comment` / `--no-share` | flag | false | Desativa cada ação |
| `--target` | list | — | Engaja só posts de empresa/pessoa-alvo (repetível) |
| `--save-targets` | flag | false | Persiste os `--target` (reuso futuro) |
| `--resume` | path | auto | Override do currículo |
| `--dry-run` | flag | false | Loga decisões/comentários sem agir |
| `--scheduled` | flag | false | Pula se já rodou hoje |
| `--force` | flag | false | Ignora skip-today |

```bash
uv run main.py content engage                             # sorteia 1-20 posts
uv run main.py content engage --posts-number 5
uv run main.py content engage --min-post 3 --max-post 8
uv run main.py content engage --target "Nubank" --target "Stone" --save-targets
```

O comentário tem A/B test embutido (variantes `insight`/`pergunta`); a variante usada
é gravada e aparece no relatório semanal. Para aprovação humana antes de postar,
use `/engage` no bot (human-in-loop).

---

### `content autopost`

Gera post autoral via LLM, aprova no Telegram ou CLI, publica no LinkedIn.
Ver `docs/specs/autopost-feature.md`.

```bash
uv run main.py content autopost                           # gera draft + envia p/ Telegram
uv run main.py content autopost --source manual --topic "..." --dry-run
uv run main.py content autopost --no-telegram             # printa stdout
uv run main.py content autopost --list                    # drafts pendentes + aprovados
uv run main.py content autopost --approve <draft_id>      # aprova via CLI
uv run main.py content autopost --publish-approved        # publica todos aprovados
```

**Fluxo assíncrono:** `autopost` gera e sai → usuário aprova (Telegram tap **ou** `--approve`) → `--publish-approved` publica.

| Flag | Descrição |
|------|-----------|
| `--source rss\|commit\|template\|manual` | Fonte de conteúdo |
| `--topic "string"` | Tema custom (manual) |
| `--format snippet\|story\|dissertativo\|contrarian` | Formato do post |
| `--dry-run` | Gera + Telegram preview, não registra pending |
| `--no-telegram` | Stdout apenas |
| `--scheduled` | Respeita skip-today |
| `--list` | Lista drafts pending + approved com IDs |
| `--approve <id>` | Aprova draft por ID (CLI) |
| `--publish-approved` | Drena `getUpdates` Telegram + publica todos aprovados |

---

## `profile` — perfil LinkedIn

### `profile capture`

Captura snapshots de SSI + profile views + aparições em pesquisa. Once-per-day por padrão.
Sem flags = captura todas as métricas.

```bash
uv run main.py profile capture                  # todas (SSI + views + appearances)
uv run main.py profile capture --ssi            # só SSI
uv run main.py profile capture --views          # só profile views
uv run main.py profile capture --appearances    # só aparições em pesquisa
uv run main.py profile capture --ssi --views    # combinações possíveis
uv run main.py profile capture --force          # força recaptura mesmo se já capturou hoje
```

---

### `profile skills`

Gerencia competências do perfil LinkedIn. Três modos: args diretos, config local ou top skills do tracker.

**Setup:** adicionar `LINKEDIN_PROFILE_SLUG=sr-marinho` no `.env`.

```bash
# Listar competências atuais (abre browser)
uv run main.py profile skills list

# Modo B: args diretos (add é idempotente: pula as que já existem)
uv run main.py profile skills add "Python" "AWS" "Docker"
uv run main.py profile skills add "Python" --force      # readiciona mesmo se já existir
uv run main.py profile skills delete "Java"

# Modo A: config local (set + sync)
uv run main.py profile skills set "Python" "AWS" "Docker" "Kubernetes"
uv run main.py profile skills show-desired
uv run main.py profile skills sync           # deleta não-desejadas, adiciona faltantes

# Modo C: top skills dos jobs avaliados
uv run main.py profile skills sync-from-tracker --top 15 --dry-run
uv run main.py profile skills sync-from-tracker

# Modo D: seed versionado (data/linkedin_skills_seed.txt)
uv run main.py profile skills seed --dry-run        # lista normalizada, sem browser
uv run main.py profile skills seed                  # sync: perfil = seed (deleta fora da lista)
uv run main.py profile skills seed --add-only       # só adiciona faltantes (não deleta)
uv run main.py profile skills seed --limit 100      # trunca nas 100 primeiras (prioridade = ordem)
uv run main.py profile skills seed --from-file outro.txt
```

Seed (`data/linkedin_skills_seed.txt`): 1 skill/linha, `#` = comentário; ordem =
prioridade. Normalizado (trim + dedupe case-insensitive) ao carregar. `add`/`seed`
param sozinhos ao detectar o limite de competências do LinkedIn (log
`LinkedIn skill limit reached at N`). Rode com `HEADLESS=FALSE` para acompanhar.

> Seletores best-effort (DOM obfuscado). Se retornar `✗`, rode sem `--headless` para inspecionar.

---

### `profile views`

Análise de visualizações de perfil (janela 90 dias).

```bash
uv run main.py profile views show            # tendência + aceleração
uv run main.py profile views show --window 14
uv run main.py profile views list            # snapshots diários brutos
```

---

### `profile ssi`

Social Selling Index: score e histórico por pilar.

```bash
uv run main.py profile ssi show              # score atual + breakdown (brand/people/insights/rels)
uv run main.py profile ssi list              # histórico de snapshots
```

---

### `profile appearances`

Aparições em resultados de pesquisa LinkedIn (janela ~7 dias).

```bash
uv run main.py profile appearances show      # contagem atual + tendência
uv run main.py profile appearances list      # histórico de snapshots
```

---

## `insights` — relatórios e dashboard

### `insights report`

Relatório semanal com candidaturas, conexões, engagement, autopost, follow-up, SSI, metas, funis de eventos e latência.

```bash
uv run main.py insights report                              # semana atual
uv run main.py insights report --prev                       # semana anterior
uv run main.py insights report --week 2026-W25              # semana específica
uv run main.py insights report --year 2026                  # resumo anual
uv run main.py insights report --telegram                   # envia via Telegram
uv run main.py insights report --scheduled                  # Telegram uma vez por semana
uv run main.py insights report --only summary,autopost,goals
uv run main.py insights report --skip ssi,latency
uv run main.py insights report --image --telegram           # envia como imagem PNG
```

**Seções disponíveis:** `summary`, `ssi`, `engagement`, `autopost`, `followup`, `goals`, `site`, `level`, `rejection`, `skills`, `failures`, `funnels`, `latency`

| Flag | Descrição |
|------|-----------|
| `--only SECTIONS` | Inclui apenas as seções listadas (vírgula-separadas) |
| `--skip SECTIONS` | Exclui as seções listadas |
| `--image` | Renderiza PNG via Playwright Chromium headless |
| `--telegram` | Envia texto **ou** imagem (com `--image`) via Telegram |
| `--scheduled` | Só envia se não enviou ainda na semana |

---

### `insights dashboard`

Dashboard TUI ao vivo (textual): candidaturas, engagement, autopost, SSI e
progresso de metas. `r` atualiza, `q` sai.

```bash
uv run main.py insights dashboard
```

---

## `config` — configuração do sistema

### `config provider`

Switch LLM backends without editing `.env` manually.

```bash
uv run main.py config provider show
uv run main.py config provider set eval claude
uv run main.py config provider set eval langchain --model llama3.1:8b
uv run main.py config provider set llm claude
uv run main.py config provider set llm langchain --model deepseek-r1:14b
```

| Target | Description |
|--------|-------------|
| `eval` | AI for job evaluation (match/fit analysis) |
| `llm` | AI for form Q&A (answering unknown questions) |

```bash
# Manage API keys
uv run main.py config provider key set claude <API_KEY>
uv run main.py config provider key show
```

---

### `config db`

Postgres backend management (no-op em modo JSON local).

```bash
uv run main.py config db check
uv run main.py config db init
uv run main.py config db migrate
uv run main.py config db status
```

---

### `config goals`

Metas semanais; o relatório semanal avisa o que está atrás.

```bash
uv run main.py config goals show
uv run main.py config goals set applications 12
uv run main.py config goals set connections 60
```

Métricas suportadas: `applications`, `connections`, `posts`, `comments`.

---

### `config telegram-topics`

Divide o grupo Telegram em **tópicos** (sessões do modo fórum) — cada feature manda
sua saída direto na sessão certa. Roteamento via `message_thread_id`.

Pré-requisito: ativar **Tópicos** nas configs do grupo e o bot ser admin.

```bash
uv run main.py config telegram-topics setup    # cria os tópicos que faltam + salva thread_ids
uv run main.py config telegram-topics list     # mostra tópicos e thread_ids configurados
uv run main.py config telegram-topics reset    # limpa o mapa (não apaga os tópicos no Telegram)
```

**Tópicos criados:** `📊 Relatórios` (report/hired), `📝 Autopost` (drafts/aprovação/falhas),
`🤝 Engage`, `💬 Follow-up`, `🚨 Alertas` (checkpoint/CAPTCHA), `📡 Status` (candidaturas).

Sem mapa configurado, tudo continua caindo no chat principal (degradação graciosa).
