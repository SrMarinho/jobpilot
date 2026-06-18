# Spec — Autopost LinkedIn (posts autorais com LLM + Telegram approval)

## 1. Resumo

Pipeline que gera posts autorais no LinkedIn via LLM, envia draft pro Telegram pra aprovação humana, e publica via Playwright em horário pico. Objetivo: subir SSI sem virar trabalho manual.

Cadência: **2 posts/semana** (terça + sexta, 09h BRT + jitter). Modo `--dry-run` permite testar mais frequentemente sem publicar.

Distinta de `engage-feature.md` (like/comment/share em posts alheios). Esta é criação de conteúdo próprio.

## 2. Comportamento

### Pipeline

```
[trigger: scheduled OU /autopost no Telegram]
       ↓
[source pick: weekday template | rss | git log | manual topic]
       ↓
[LLM draft via LLMProvider.complete(prompt)]
       ↓
[validation pós-LLM: char count <= 900, senão regera 1x]
       ↓
[Telegram envia draft + inline buttons [✅ Aprovar | ✏️ Editar | ❌ Rejeitar | 🔄 Regenerar]]
       ↓                     ↓                ↓                ↓
   [Aprovar]              [Editar]       [Rejeitar]      [Regenerar]
       ↓                     ↓                ↓                ↓
[Playwright publica]   [aguarda texto novo]  [discard]    [loop draft]
       ↓
[salva em posted_history.json]
```

Scheduled runs **sempre passam por Telegram**. Se user não responder em 4h, draft expira (manager mark expired no próximo run).

### LLM Prompt

**Regras duras:**
- Curto e objetivo. Alvo 400-700 chars, hard cap 900.
- Primeira linha = hook forte (contrarian / quantificado / vulnerabilidade / pergunta / declaração polêmica)
- Tom pessoal, primeira pessoa
- Toda frase carrega peso, zero filler
- Quebras de linha frequentes (mobile-first)
- Encerra com pergunta ou CTA curto (opcional se quebrar fluidez)
- 2-4 hashtags relevantes no fim

**Formatos suportados:**

| Formato | Estrutura | Quando usar |
|---------|-----------|-------------|
| snippet | 1 dica em 3-5 linhas | Tip técnico, código curto |
| story | situação → ação → lição (máx 6 linhas) | Build-in-public, bug story |
| dissertativo | tese + argumento + conclusão | Opinião técnica |
| contrarian | opinião polêmica + reasoning + convite ao debate | Posicionamento/SSI boost |

### Fontes de conteúdo

| Fonte | Implementação | Quando |
|-------|---------------|--------|
| `template` (default) | weekday → format default + tema sorteado | Scheduled run |
| `rss` | `feedparser` em HN, dev.to, Python Weekly, Node Weekly | Sexta default |
| `commit` | `git log --since="1 week"` parse | Terça default (build-in-public) |
| `manual` | user manda tema via `/autopost_topic <tema>` ou `--topic` | Ad-hoc |

### Filtros de segurança

Pós-LLM, antes de mandar Telegram:
- Reject se contém palavras de empresa proibida (env `AUTOPOST_BLOCKLIST`)
- Reject se char count > 900 após 1 regen
- Reject se >5 hashtags
- Reject se contém código com placeholder não preenchido (`TODO`, `FIXME`, `<...>`)

## 3. Arquitetura

### Arquivos novos

| Path | Função |
|------|--------|
| `src/automation/pages/feed_page.py` | Page object: abre composer, digita, publica |
| `src/core/use_cases/post_drafter.py` | Gera draft via `LLMProvider.complete()` |
| `src/core/use_cases/post_sources.py` | Source pickers: rss/commit/template/manual |
| `src/core/use_cases/posted_tracker.py` | Persist em `posted_history.json` |
| `src/automation/tasks/autopost_manager.py` | Orquestrador end-to-end |
| `src/interfaces/cli/autopost/command.py` | Typer cmd |
| `src/interfaces/cli/autopost/logic.py` | `resolve_autopost_config()` |
| `.local/startup_autopost.bat` + `.ps1` | Wrapper Windows (com `-NoProfile`) |
| `.local/jobpilot_autopost_task.xml` | Task Scheduler XML |
| `scripts/inspect_linkedin_composer.py` | DOM dump util (Fase 0) |

### Arquivos modificados

- `src/interfaces/cli/router.py` — registra autopost
- `src/bot/telegram_bot.py` — `/autopost`, `/autopost_topic`, `/autopost_format`, callbacks, step `autopost_edit`
- `src/core/use_cases/monthly_report.py` — soma autopost counts
- `.gitignore` — confirma `.local/files/posted_history.json` ignorado

### Padrões reusados

- LLM: `LLMProvider.complete(prompt)` (`src/core/ai/llm_provider.py:35-40`)
- Telegram stateful: `_step` + `_form` (`telegram_bot.py:121,152`); botões `send(..., buttons=[[{text,data}]])` (linha 44); callback `_handle_callback()` (linha 180)
- Async spawn: `threading.Thread(target=_run_X_async, daemon=True)` + `run_async(coro)`
- Persistence JSON: `_load()`/`_save_X()` (`src/interfaces/cli/persistence.py:37,56`), `ensure_ascii=False, indent=2`
- CLI: `@app.command()` + `set_run_context()` + `resolve_*_config()` + `run_async(run_browser(_work, headless))` (igual `src/interfaces/cli/connect/command.py:12-71`)

## 4. Scheduling

Task Scheduler XML: 2 `TimeTrigger`:
- Terça 09:00 BRT, `RandomDelay=PT30M`
- Sexta 09:00 BRT, `RandomDelay=PT30M`

Action: `wscript.exe run_hidden.vbs startup_autopost.bat`

`startup_autopost.bat` (thin shim, **com -NoProfile**):
```bat
@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "F:\Documentos\Projetos\Code\jobpilot\.local\startup_autopost.ps1"
```

`startup_autopost.ps1`:
```powershell
$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location 'F:\Documentos\Projetos\Code\jobpilot'
& 'C:\Users\Sr. Marinho\.local\bin\uv' run main.py --headless autopost --scheduled
```

## 5. CLI

```
uv run main.py autopost
  [--source rss|commit|template|manual]   # default: template do weekday
  [--topic "string"]                       # required se source=manual
  [--format snippet|story|dissertativo|contrarian]  # override weekday default
  [--dry-run]                              # gera + Telegram, mas skip publish (mesmo se aprovado)
  [--no-telegram]                          # gera + printa stdout (debug)
  [--scheduled]                            # respeita weekly_limit, marca run_date
```

## 6. Persistence — `posted_history.json`

```json
{
  "posts": [
    {
      "id": "uuid",
      "ts": "2026-06-18T09:14:33-03:00",
      "source": "commit",
      "format": "story",
      "topic": "refactor browser locks",
      "content": "...",
      "url": "https://www.linkedin.com/feed/update/urn:li:activity:..."
    }
  ],
  "last_run_date": "2026-06-17",
  "weekly_count_week": "2026-W25",
  "weekly_count": 2,
  "drafts_pending": [
    {
      "id": "uuid",
      "telegram_msg_id": 123,
      "created_at": "2026-06-18T09:14:00",
      "expires_at": "2026-06-18T13:14:00",
      "content": "..."
    }
  ]
}
```

## 7. Telegram bot — comandos novos

| Comando | Ação |
|---------|------|
| `/autopost` | Trigger manual com source=template (default weekday). Envia draft + botões. |
| `/autopost_topic <tema>` | Manual source com tema custom |
| `/autopost_format <tipo>` | Force format pro próximo draft |
| `/autopost_list` | Lista últimos 5 posts publicados + pending drafts |

**Callbacks:**
- `autopost_approve:<id>` → posta
- `autopost_edit:<id>` → seta `_step="autopost_edit"`, aguarda texto novo
- `autopost_regen:<id>` → regenera mesmo source/format
- `autopost_reject:<id>` → discard

## 8. Métricas

`monthly_report.py` agrega:
- Total posts publicados no mês
- Breakdown por source (rss/commit/template/manual)
- Breakdown por format (snippet/story/dissertativo/contrarian)
- Drafts gerados / drafts aprovados / drafts rejeitados / drafts expirados (approval rate %)
- Avg char count

## 9. Trade-offs & Riscos

| Decisão | Por quê | Risco | Mitigação |
|---------|---------|-------|-----------|
| Telegram approval obrigatório | LLM hallucination = dano reputação | Atrito, user pode ignorar | Notificação push + expira em 4h |
| 2/sem (não 5) | Algoritmo penaliza spam, sustentável | SSI sobe devagar | Configurável via env |
| Playwright (não API oficial) | LinkedIn API requer partner approval | DOM muda | Fase 0 inspect + selectors centralizados |
| Hard cap 900 chars | Força concisão (preferência user) | LLM pode cortar mal | Regen automático 1x |
| Drafts pendentes em JSON | Consistência com projeto | Race se 2 managers | Lock file (igual browser) |
| Dry-run flag | Permite testar cadência | Mais código condicional | Bem isolado no manager |

## 10. Fases de implementação (~5-7h)

1. **Fase 0** (30min) — `scripts/inspect_linkedin_composer.py` dump DOM do composer + post publicado
2. **Fase 1** (1h) — `feed_page.py` + `posted_tracker.py`
3. **Fase 2** (1.5h) — `post_drafter.py` + `post_sources.py` (RSS, git log, weekday template, manual)
4. **Fase 3** (1h) — `autopost_manager.py` (source → draft → telegram pending → wait callback → publish)
5. **Fase 4** (1.5h) — Telegram handlers + callbacks + stateful edit
6. **Fase 5** (45min) — CLI command + logic + router + `--scheduled` flow
7. **Fase 6** (45min) — XML + bat + ps1 + monthly_report integration

## 11. Verificação E2E

1. `uv run main.py autopost --dry-run --source manual --topic "teste hook contrarian"` → Telegram recebe draft com botões
2. Click "Aprovar" em dry-run → log `[dry-run] would publish`, skip Playwright publish
3. Repetir sem `--dry-run` em conta de teste real → Playwright posta, `posted_history.json` populated com URL
4. `uv run main.py autopost --source commit` → draft baseado em git log da semana
5. `uv run main.py autopost --source rss` → draft baseado em top RSS item
6. PS1 manual: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .local\startup_autopost.ps1`
7. Aguardar trigger Ter/Sex 9h → chain xml→vbs→bat→ps1→uv

## 12. Não-escopo

- Posts com imagem/vídeo (texto only)
- Repost/share alheio (já em engage-feature)
- A/B test de hooks
- Auto-resposta a comentários nos próprios posts
- Translation EN/PT (PT-BR only)
- Análise de SSI real via scrape (futuro)
