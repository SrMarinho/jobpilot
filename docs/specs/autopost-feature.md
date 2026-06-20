# Spec — Autopost LinkedIn (posts autorais com LLM + Telegram approval)

> **Status: IMPLEMENTADO.** Este doc reflete o código em produção. Pontos ainda
> não verificados ao vivo estão marcados com ⚠️.

## 1. Resumo

Pipeline que gera posts autorais no LinkedIn via LLM, envia draft pro Telegram pra
aprovação humana, e publica via Playwright. Objetivo: subir SSI sem virar trabalho
manual.

Cadência: **2 posts/semana** (terça + sexta, 09h BRT + jitter `RandomDelay=PT30M`).
Modo `--dry-run` testa sem publicar.

Distinta de `engage-feature.md` (like/comment/share em posts alheios). Esta é
criação de conteúdo próprio.

### Arquitetura publish-on-approval (decisão central)

Geração e publicação são **processos separados**:

- **Gerar** = só LLM, **sem browser**. O run scheduled (CLI one-shot) gera o draft,
  registra como `pending`, manda pro Telegram com botões e **sai** (exit 0). Não
  segura processo esperando aprovação.
- **Publicar** = abre browser. Acontece no **bot persistente**: o callback
  `autopost_approve:<id>` dispara o `BrowserTaskRunner`, que abre Chrome sob o
  browser lock (serializado com apply/connect/engage) e publica.

Logo: a máquina scheduled não precisa de browser aberto na hora certa; o bot
persistente (já rodando) é quem publica quando o humano aprova.

## 2. Comportamento

### Pipeline

```
[trigger: scheduled CLI one-shot OU /autopost no bot]
       ↓
[source pick: weekday template | rss | git log | manual topic]
       ↓
[LLM draft via LLMProvider.complete(prompt)]  (async, qwen3:8b)
       ↓
[strip <think>…</think> + validate (80..900 chars, hashtags, placeholder, blocklist); regen 1x]
       ↓
[add_draft(status=pending) + Telegram send com botões]
       ↓  CLI scheduled EXIT aqui
       ↓
─── bot persistente recebe callback ───
       ↓                 ↓                ↓                ↓
   [Aprovar]          [Editar]        [Rejeitar]      [Regenerar]
       ↓                 ↓                ↓                ↓
[runner abre browser  [step=          [status=        [status=REJECTED
 sob lock, publica]    autopost_edit]  REJECTED]       + nova geração]
       ↓                 ↓
[mark_posted + URL]   [valida texto novo → update_content → reenvia botões]
       ↓
[best-effort SSI snapshot (SSIPage + SSITracker)]
```

Se humano não responder em **4h**, draft expira: `expire_stale()` roda no início
do próximo `run_autopost` e marca `status=expired`.

### LLM Prompt

Modelo: **qwen3:8b via Ollama** (LangChain provider). DeepSeek foi abandonado.
Provider obtido via `get_eval_provider()`; `warmup_llm_providers()` no boot do run.
`LLMProvider.complete(prompt)` é **async**.

**Regras duras (em `PostDrafter._build_prompt`):**
- Alvo 400-700 chars, hard cap 900.
- Primeira linha = hook forte (contrarian / número / vulnerabilidade / pergunta).
- Primeira pessoa, toda frase carrega peso, zero filler.
- Quebras de linha frequentes (mobile-first).
- Encerra com pergunta ou CTA curto.
- 2-4 hashtags relevantes no fim. Máx 1 emoji.
- Currículo (1500 chars) injetado pra autenticidade.

**Formatos suportados** (`_FORMAT_GUIDE`):

| Formato | Estrutura |
|---------|-----------|
| snippet | 1 dica técnica em 3-5 linhas |
| story | situação → ação → lição (máx 6 linhas), build-in-public |
| dissertativo | tese + argumento + conclusão |
| contrarian | opinião polêmica defensável + reasoning + convite ao debate |

### Fontes de conteúdo (`post_sources.py`)

| Fonte | Implementação | Quando |
|-------|---------------|--------|
| `template` (default) | `default_format_for_today()` + tema sorteado do pool `_TOPICS` | Dia comum |
| `commit` | `git log --since="1 week"` | Terça default (build-in-public) |
| `rss` | `feedparser` em HN / dev.to (fallback gracioso se sem rede) | Sexta default |
| `manual` | `/autopost_topic <tema>` ou `--topic` | Ad-hoc |

`default_source_for_today()`: Ter→commit, Sex→rss, resto→template.
`pick_content(source, topic) -> (topic, context)`.

### Validação pós-LLM (`validate_draft`)

Strip `<think>…</think>` antes. Reject se:
- vazio / `< 80` chars / `> 900` chars
- placeholder não preenchido (`TODO` / `FIXME` / `<...>` / `<placeholder>`)
- `> 5` hashtags
- conteúdo blacklisted (reusa `is_blacklisted` de `engagement_handler`)

## 3. Arquitetura

### Arquivos novos

| Path | Função |
|------|--------|
| `src/automation/pages/feed_composer_page.py` | `FeedComposerPage`: abre composer, digita, publica, captura URL. ⚠️ selectors aria best-effort, não verificado ao vivo |
| `src/core/use_cases/post_drafter.py` | `PostDrafter` + `validate_draft()`. Espelha `engagement_handler` |
| `src/core/use_cases/post_sources.py` | Source pickers: template/commit/rss/manual |
| `src/core/use_cases/posted_tracker.py` | `PostedTracker` em `posted_history.json`. Espelha `EngagedPostsTracker` |
| `src/automation/tasks/autopost_manager.py` | `AutopostManager.generate()` — só LLM, sem browser |
| `src/interfaces/cli/autopost/command.py` | `register_autopost_command(app)` |
| `src/interfaces/cli/autopost/logic.py` | `resolve_autopost_config()` + `run_autopost()` + `_approval_buttons()` |
| `.local/startup_autopost.bat` + `.ps1` | Wrapper Windows (force-added, gitignored) |
| `.local/jobpilot_autopost_task.xml` | Task Scheduler XML |
| `scripts/inspect_linkedin_composer.py` | DOM dump util (Fase 0, opcional) ⚠️ ainda não criado |

> **`feed_page.py` NÃO é novo.** Já existe (engage, read-only: like/comment/share).
> O composer/publish é page object separado: `feed_composer_page.py`.

### Arquivos modificados

- `src/interfaces/cli/router.py` — `register_autopost_command(app)` (entre engage e report)
- `src/bot/` (package refatorado) — handlers autopost:
  - `router.py` (`UpdateRouter`): comandos `/autopost`, `/autopost_topic`, `/autopost_format`, `/autopost_list`
  - `conversation.py` (`ConversationFlow`): callbacks `autopost_*` + step `autopost_edit`
  - `runner.py` (`BrowserTaskRunner`): `launch_autopost_generate` (detached, sem lock) + `launch_autopost_publish` (sob lock) + `_capture_ssi`
  - `client.py` (`TelegramClient`): `send(text, buttons=...)`, `register_commands()`
- **Report (package `report/`, não `monthly_report.py`)**:
  - `repository.py` — `autopost()` carrega `posted_history.json`
  - `metrics.py` — `MetricsCalculator.autopost(period)`
  - `builder.py` — `ReportBuilder.weekly()` inclui `"autopost"`
  - `formatter.py` — `_autopost_block()` (omite se sem atividade)
- `pyproject.toml` — dep direta `feedparser>=6.0`
- `.gitignore` — `.local/files/posted_history.json` ignorado (runtime data)

### Padrões reusados

- LLM: `get_eval_provider()` + `await provider.complete(prompt)` + `warmup_llm_providers()`
- Resume: `load_resume_text()` de `engagement_handler` (não duplicar parsing)
- Blacklist: `is_blacklisted()` de `engagement_handler`
- Persistence JSON: save atômico (tmp→replace), `ensure_ascii=False, indent=2`, hard cap, chaves `week`/`month`/`day` via `strftime`. Espelha `EngagedPostsTracker`
- Browser lock: `acquire_browser_lock(name)` / `_release_browser_lock(lock, name)` de `interfaces/cli/browser.py`
- Skip-today scheduled: `is_already_ran_today("autopost")` / `save_ran_today("autopost")` de `persistence.py`
- SSI: `SSIPage.scrape_with_goto()` + `SSITracker.already_captured_today()` (best-effort, nunca fatal)

## 4. Scheduling

Task Scheduler XML (`jobpilot_autopost_task.xml`): `CalendarTrigger` `ScheduleByWeek`,
dias **Tuesday + Friday**, 09:00, `RandomDelay=PT30M`, `MultipleInstancesPolicy=IgnoreNew`.

Action: `wscript.exe run_hidden.vbs startup_autopost.bat` (sem janela).

`startup_autopost.bat`: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File ...ps1`.

`startup_autopost.ps1` (espelha `startup_engage.ps1`):
- força `LLM_PROVIDER_EVAL=langchain`, `LANGCHAIN_MODEL=qwen3:8b`, `OLLAMA_BASE_URL`
- checa Ollama (`GET /api/tags`); se down → `Start-Process ollama serve -WindowStyle Hidden` + espera
- **retry exponencial 5x** (30/60/120/240/480s)
- `uv` path absoluto → `main.py autopost --scheduled`

## 5. CLI

```
uv run main.py autopost
  [--source rss|commit|template|manual]   # default: weekday
  [--topic "string"]                       # tema custom (manual)
  [--format snippet|story|dissertativo|contrarian]
  [--dry-run]                              # gera + manda Telegram preview, NÃO registra pending
  [--no-telegram]                          # gera + printa stdout (debug)
  [--scheduled]                            # respeita skip-today + marca run
  [--force]                                # ignora skip-today no modo scheduled
```

`resolve_autopost_config()` early-exit (None) se `scheduled and not force and
is_already_ran_today("autopost")`. Senão: warmup + `save_ran_today` + retorna cfg.

## 6. Persistence — `posted_history.json`

Duas listas: `drafts` (todo draft gerado, com `status`) + `posts` (publicados).
Hard cap 300 por lista. Save atômico.

```json
{
  "drafts": [
    {
      "id": "ab12cd34ef56",
      "created_at": "2026-06-18T09:14:00",
      "expires_at": "2026-06-18T13:14:00",
      "status": "pending | approved | rejected | expired",
      "source": "commit", "format": "story", "topic": "...",
      "content": "...", "chars": 461,
      "telegram_msg_id": 123,
      "week": "2026-W25", "month": "2026-06", "day": "2026-06-18"
    }
  ],
  "posts": [
    {
      "id": "...", "ts": "2026-06-18T09:20:11",
      "source": "commit", "format": "story", "topic": "...",
      "content": "...",
      "url": "https://www.linkedin.com/feed/update/urn:li:activity:...",
      "week": "2026-W25", "month": "2026-06", "day": "2026-06-18"
    }
  ]
}
```

`counts_for_week(week_key)` → published / by_source / by_format / generated /
approved / rejected / expired / avg_chars.

## 7. Telegram bot — comandos novos

| Comando | Ação |
|---------|------|
| `/autopost` | Gera draft (source=weekday) + botões. Geração detached (sem lock) |
| `/autopost_topic <tema>` | Manual source com tema custom |
| `/autopost_format <tipo>` | Force format no próximo draft |
| `/autopost_list` | Últimos 5 posts publicados + contagem pending |

**Callbacks** (`ConversationFlow._handle_autopost_callback`, admin-gated):
- `autopost_approve:<id>` → `runner.launch_autopost_publish(id)` (abre browser sob lock)
- `autopost_edit:<id>` → `_step="autopost_edit"`, aguarda texto → `validate_draft` → `update_content` → reenvia botões
- `autopost_regen:<id>` → `status=REJECTED` + `launch_autopost_generate(mesmo source/topic/format)`
- `autopost_reject:<id>` → `status=REJECTED`

Guard: se draft não existe ou `status != pending` → "⚠️ Draft expirado ou já processado".

## 8. Métricas — relatório semanal

`MetricsCalculator.autopost(period)` (filtra por `period.key` = week):
- published (total) + by_source + by_format
- generated / approved / rejected / expired → approval rate
- avg char count

Render: `ReportFormatter._autopost_block()` — retorna "" se sem atividade (zeros).
Espelha `_engagement_block` / `_ssi_block`.

## 9. Trade-offs & Riscos

| Decisão | Por quê | Risco | Mitigação |
|---------|---------|-------|-----------|
| Telegram approval obrigatório | LLM hallucination = dano reputação | Atrito | Expira em 4h |
| Gera sem browser, publica no bot | Scheduled não precisa segurar Chrome esperando humano | Bot precisa estar rodando p/ publicar | Bot é serviço persistente |
| 2/sem (não 5) | Algoritmo penaliza spam | SSI sobe devagar | Configurável |
| Playwright (não API oficial) | LinkedIn API requer partner approval | DOM muda | ⚠️ selectors aria, validar ao vivo |
| Hard cap 900 chars | Concisão (preferência user) | LLM corta mal | Regen 1x |
| Browser lock compartilhado | Serializa com apply/connect/engage | Espera se outra task roda | Aceitável (1 task/vez) |

## 10. Fases de implementação — DONE

1. ~~**Fase 0** — `scripts/inspect_linkedin_composer.py` DOM dump~~ ⚠️ pulada; selectors aria diretos no `FeedComposerPage` (não validados ao vivo)
2. ✅ `posted_tracker.py` (espelha `EngagedPostsTracker`) + `feed_composer_page.py`
3. ✅ `post_drafter.py` + `post_sources.py` (RSS via feedparser, git log, template, manual)
4. ✅ `autopost_manager.py` (source → draft, sem browser)
5. ✅ Telegram package: callbacks + step `autopost_edit` no `ConversationFlow`, publish no `BrowserTaskRunner`
6. ✅ CLI command + logic + router + `--scheduled`/`--force`
7. ✅ XML + bat + ps1 + métrica no report package

## 11. Verificação E2E

Feito:
- ✅ Geração real: Ollama qwen3:8b produziu draft contrarian 461 chars, hook forte, `<think>` stripado, validação passou
- ✅ Report monta com bloco autopost (omitido quando zero)
- ✅ Lint (ruff check) limpo, imports ok

Pendente (precisa conta/ambiente real):
- ⚠️ `FeedComposerPage.publish()` contra DOM real do composer LinkedIn → único caminho não verificado
- `uv run main.py autopost --dry-run --source manual --topic "..."` → Telegram recebe preview
- Aprovar no bot → runner abre browser, publica, `posted_history.json` ganha post + URL
- Trigger Ter/Sex 9h → chain xml→vbs→bat→ps1→uv

## 12. Não-escopo

- Posts com imagem/vídeo (texto only)
- Repost/share alheio (já em engage-feature)
- A/B test de hooks
- Auto-resposta a comentários nos próprios posts
- Translation EN/PT (PT-BR only)

> SSI: **não** é mais não-escopo. Autopost captura SSI best-effort após publicar
> (`SSIPage` + `SSITracker`, gated por `already_captured_today()`), igual ao engage.
