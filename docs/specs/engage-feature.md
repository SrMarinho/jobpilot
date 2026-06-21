# Spec — LinkedIn Engage Feature

> Status: **proposed**
> Owner: solo dev
> Target site: LinkedIn feed
> Depende de: LLM provider já configurado (Claude/DeepSeek/Ollama via warmup)

---

## 1. Resumo

Bot interage com o feed do LinkedIn (curtir + comentar + share opcional) usando o LLM
configurado para gerar **comentários curtos** alinhados ao perfil do currículo.
Executado **3 a 5 vezes por dia em horários staggered**, com dedupe e rate-limit.

Objetivos:
- Aumentar visibilidade no algoritmo do LinkedIn (engagement consistente)
- Construir presença passiva na rede sem effort manual
- Manter coerência com o título profissional do currículo

Não-objetivos:
- Engajar em conteúdo controverso
- Comentar próprios posts
- Substituir interação humana real (é complemento, não replacement)

---

## 2. Comportamento

### 2.1 Pipeline por execução

```
1. Open feed (https://www.linkedin.com/feed/)
2. Scroll N vezes para carregar ~20 posts
3. Para cada post:
     - Extrair URN, autor, texto
     - Skip se already_engaged(urn)
     - Skip se autor == self
     - Skip se conteúdo blacklisted (política, religião, polêmicas)
     - Skip se idioma != PT/EN
     - LLM: should_engage(post_text, resume) → True/False
4. Pega os primeiros K relevantes (K = --max-posts, default 2)
5. Para cada selecionado:
     - LIKE  (sempre)
     - COMMENT  (LLM gera 5-15 palavras, mesmo idioma do post)
     - SHARE  (1 em 5, só se --enable-share)
6. mark_engaged(urn, actions, comment_text)
7. Telegram opcional: "Engaged: 2 posts (1 like+comment, 1 like only)"
```

### 2.2 LLM prompt (comentário)

```
Você é {user_name}, {user_headline}.
Você está engajando em um post do LinkedIn como peer profissional.

Currículo (resumo):
{resume_text[:500]}

Post de {author}:
"""
{post_text}
"""

Escreva 1 comentário curto (5-15 palavras), profissional, no mesmo idioma do post.
Pode trazer um insight técnico, agradecimento concreto, ou pergunta relevante.

Regras estritas:
- NÃO use emojis
- NÃO mencione que está procurando emprego
- NÃO use clichês ("ótimo post!", "concordo plenamente", "muito bom!")
- NÃO seja sycophantic
- Se não tiver algo de valor a dizer, retorne string vazia

Comentário:
```

### 2.3 Filtros de segurança

Os filtros puros vivem em `src/core/use_cases/content_filters.py` (léxicos +
funções), separados da classe `EngagementHandler` (`engagement_handler.py`).

| Filtro | Regra |
|---|---|
| Blacklist keywords | política, eleição, religião, racismo, gun control, abortion, vacina (anti/pró), sexo, etc. → skip |
| Post comentável | strip de URL/emoji; `is_commentable_post` exige ≥ 6 palavras de conteúdo. Post fino/só-link/só-imagem é pulado (senão o modelo inventa) |
| Comprimento mínimo do comentário | ≥ 5 palavras (evita "👍"/"+1") |
| Comprimento máximo do comentário | ≤ 200 chars (curto, evita parecer spam) |
| Foreign-tech | comentário citando linguagem/framework nomeado **ausente** do post → rejeita (stack alucinado, ex: Python em post Java/Spring) |
| **Grounding (anti-alucinação)** | `comment_is_grounded`: exige overlap léxico (prefixo 5 chars, tolera flexão) entre comentário e post. Zero overlap = fato inventado (ex: "RPA em produção" num post só com link) → rejeita. 2 tentativas; se nenhuma ancora, **não comenta** |
| Limite diário | 5 posts/dia (hard cap) |
| Limite semanal | 25 posts/semana (LinkedIn anti-spam) |
| Cooldown entre ações | sleep random 30-90s entre engajamentos |
| Share | default OFF (precisa `--enable-share`) |
| Dedupe | persistente por URN — nunca engajar 2x o mesmo post |

---

## 3. Arquitetura

Segue padrão Layered + Hexagonal-light já adotado no projeto.

### 3.1 Novos arquivos

```
src/automation/pages/feed_page.py
  └─ FeedPage(page, url)
       .get_posts() -> list[ElementHandle]
       .get_post_urn(post) -> str
       .get_post_text(post) -> str
       .get_post_author(post) -> str
       .like_post(post) -> bool
       .open_comment_box(post)
       .submit_comment(text) -> bool
       .share_post(post) -> bool
       .scroll_feed(n: int)

src/core/use_cases/engagement_handler.py
  └─ EngagementHandler(llm_provider, resume, user_name, user_headline)
       .is_relevant(post_text) -> bool   # blacklist + heuristic
       .generate_comment(post_text, author) -> str | None

src/core/use_cases/engaged_posts_tracker.py
  └─ EngagedPostsTracker(json_path=".local/files/engaged_posts.json")
       .already_engaged(urn) -> bool
       .mark_engaged(urn, author, actions: list[str], comment: str = "")
       .daily_count(date_iso) -> int
       .weekly_count(week_iso) -> int
       .daily_target(date_iso) -> int    # cria se não existe (random 3-5)
       .self_author_name(name)            # setter para skip dos próprios posts

src/automation/tasks/engagement_manager.py
  └─ EngagementManager(page, llm_provider, resume_path,
                       max_posts=2, enable_share=False,
                       scheduled=False, stop_event=None)
       async def run() -> EngagementResult

src/interfaces/cli/engage/command.py
  └─ register_engage_command(app)

src/interfaces/cli/engage/logic.py
  └─ resolve_engage_config(...)
  └─ run_engage_browser(page, cfg)

.local/startup_engage.bat              # shim para Task Scheduler
.local/startup_engage.ps1              # comando uv run real
.local/jobpilot_engage_task.xml        # Task Scheduler XML (3 triggers/dia)
```

### 3.2 Modificados

| Arquivo | Mudança |
|---|---|
| `src/interfaces/cli/router.py` | Registrar `engage` command |
| `src/core/use_cases/monthly_report.py` | Nova seção "Engagement" — likes / comments / shares no mês |
| `docs/cli.md` | Documentar `engage` |
| `docs/scheduled-tasks.md` | Documentar trigger engage |
| `CLAUDE.md` | Adicionar engage à seção Architecture |

### 3.3 Reuso (não criar novo)

- `src/core/ai/llm_provider.get_eval_provider()` — reusa provider já warmed up
- `src/interfaces/cli/browser.create_context` + `run_browser` — Playwright setup
- `src/interfaces/cli/browser._another_instance_active` — defesa contra paralelismo
- `src/utils/logger.set_run_context("engage")`
- `src/utils/telegram.send_telegram` — daily summary

### 3.4 Selectors esperados (LinkedIn feed, 2026)

Validar via `scripts/inspect_linkedin_feed.py` (criar análogo ao
`inspect_linkedin_people.py` que já fizemos para o connect):

| Elemento | Seletor provável |
|---|---|
| Post container | `div.feed-shared-update-v2[data-urn]` |
| URN do post | atributo `data-urn` do container |
| Autor | `.update-components-actor__title` |
| Texto | `.update-components-text` ou `.feed-shared-text` |
| Botão Like | `button[aria-label*="Reagir"]` |
| Botão Comment | `button[aria-label*="Comentar"]` |
| Textarea comment | `[role=textbox][contenteditable=true]` |
| Submit comment | `button[aria-label*="Publicar"]` |
| Botão Share | `button[aria-label*="Compartilhar"]` |
| Confirm repost | `button:has-text("Repostar agora")` |

> **Importante:** Selectors LinkedIn mudam frequentemente. Não confiar nessa tabela —
> inspecionar DOM antes de implementar, como fizemos no fix do connect (`<a>` vs `<button>`).

---

## 4. Scheduling

### 4.1 Estratégia escolhida — 3 triggers fixos + jitter

Task Scheduler **não suporta nativamente** "execute N vezes randomicamente por dia".
Opções consideradas:

| Opção | Pro | Contra |
|---|---|---|
| 1 trigger horário + counter interno | Mais "aleatório" | 12 disparos/dia, mais ruído de log |
| **3 triggers fixos** (10h, 14h, 19h) | Simples, previsível | Menos aleatório |
| Loop interno com sleep | Random verdadeiro | Processo Python vivo 14h/dia |

**Recomendado**: 3 TimeTriggers fixos no XML. Cada execução:
1. Lê `daily_target` (calculado random 3-5 no primeiro run do dia)
2. Lê `daily_count` atual
3. Se `daily_count < daily_target`: faz 1-2 engajamentos (até bater target)
4. Senão: skip silencioso

Sleep inicial 0-30min (random) dá natural-look. Soma das execuções vai 3-5/dia.

### 4.2 Task Scheduler XML

`jobpilot_engage_task.xml` — 3 `TimeTrigger`:
- 10:00 + random 0-30min
- 14:00 + random 0-30min
- 19:00 + random 0-30min

Action: `wscript.exe run_hidden.vbs startup_engage.bat` (mesma pattern dos outros).

### 4.3 `startup_engage.ps1`

```powershell
$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location 'F:\Documentos\Projetos\Code\jobpilot'
Start-Sleep -Seconds (Get-Random -Minimum 0 -Maximum 1800)  # 0-30min jitter
& 'C:\Users\Sr. Marinho\.local\bin\uv' run main.py --headless engage --scheduled
```

---

## 5. CLI

```bash
uv run main.py engage [options]

Options:
  --max-posts INT         Max posts por execução (default 2)
  --daily-target INT      Override do daily target (default random 3-5)
  --no-like               Skip likes (só comenta)
  --no-comment            Skip comentários (só like)
  --enable-share          Habilita share, 20% chance (default OFF)
  --scheduled             Modo agendado: respeita daily/weekly limits + dedupe
  --resume PATH           Path do currículo (override do _find_resume)
  --dry-run               Não executa ações, só loga decisões + comentário LLM
```

---

## 6. Persistência

`.local/files/engaged_posts.json`:

```json
{
  "self_author": "Matheus Marinho",
  "daily_target_2026-06-18": 4,
  "daily_count_2026-06-18": 2,
  "weekly_count_2026-W25": 12,
  "engaged": [
    {
      "urn": "urn:li:activity:7234567890",
      "ts": "2026-06-18T10:23:00",
      "author": "Maria Silva",
      "actions": ["like", "comment"],
      "comment": "Real-world Node.js perf gains. Curious about p99."
    }
  ]
}
```

- Hard cap: lista `engaged` truncada nas últimas 500 entries (compactação mensal)
- Atomic write (tmp + rename) — evita corrupção se crash mid-write

---

## 7. Métricas / Observability

### 7.1 Logs (estruturados via logger já existente)

```
[engage] Found 18 posts on feed (after scroll)
[engage] Filtered: 4 relevant, 14 skipped (blacklist=3, already=8, self=1, lang=2)
[engage] Daily target: 4 | Current: 2 | Will engage 2 more
[engage] Post urn=urn:li:activity:7234... author='Maria Silva' → like + comment
[engage] Comment: 'Real-world Node.js perf gains. Curious about p99.'
[engage] Done. Liked: 2 | Commented: 2 | Shared: 0
```

### 7.2 Relatório mensal

Nova seção em `monthly_report.py`:

```
[Engagement]
Likes:     45
Comments:  38
Shares:     2
Top authors interacted: João T (4), Ana M (3), ...
```

### 7.3 Telegram opcional

Daily summary às 22h (4º trigger, opcional):
```
🤝 Engagement hoje: 4 posts (4 likes, 3 comments, 0 shares)
```

---

## 8. Trade-offs e riscos

| Risco | Mitigação |
|---|---|
| LinkedIn detecta padrão e bane conta | Limite diário/semanal + jitter + cooldown entre ações |
| LLM gera comentário ofensivo | Blacklist no prompt + validação pós-geração + limite de comprimento |
| Engajar em post fake/spam | Filtro de relevância LLM (`is_relevant`) antes de comentar |
| Comentário em idioma errado | Prompt instrui "mesmo idioma do post" + heurística simples |
| Selectors do feed quebrarem | Sigan padrão Page Object — fix isolado em 1 arquivo |
| Apply/connect rodando junto | `_another_instance_active` já bloqueia (lock fresco) |

---

## 9. Plano de implementação (fases)

1. **Fase 0 — DOM inspection**
   - `scripts/inspect_linkedin_feed.py` análogo ao de people
   - Confirmar selectors reais
2. **Fase 1 — Tracker + Handler**
   - `engaged_posts_tracker.py` + testes manuais sem browser
   - `engagement_handler.py` (LLM + blacklist), validar comentários com prompt
3. **Fase 2 — Page Object**
   - `feed_page.py` com selectors confirmados
   - Testar isolado: scroll + extract sem ações
4. **Fase 3 — Manager**
   - `engagement_manager.py` orquestrando
   - CLI `engage` command (sem --scheduled ainda)
   - Run com `--dry-run` primeiro
5. **Fase 4 — Scheduling**
   - `startup_engage.ps1` + .bat + XML
   - `--scheduled` mode com daily target/count
   - Importar Task Scheduler
6. **Fase 5 — Monthly report + Telegram**
   - Seção engagement no relatório
   - Daily summary Telegram

Total estimado: ~4-6h de codificação + 1h de debug de selectors.

---

## 10. Verificação end-to-end

```bash
# 1. Inspect DOM (gera scripts/_linkedin_feed_dump.txt)
uv run python scripts/inspect_linkedin_feed.py

# 2. Dry run (não engaja, só loga decisões)
uv run main.py engage --max-posts 3 --dry-run

# 3. Like only (sem LLM)
uv run main.py engage --max-posts 1 --no-comment

# 4. Full run
uv run main.py engage --max-posts 1

# 5. Verificar tracker
cat .local/files/engaged_posts.json | jq '.engaged[-1]'

# 6. Scheduled mode
uv run main.py engage --scheduled  # respeita limites

# 7. Import task (manual no Task Scheduler ou via PS)
schtasks /Create /XML .local\jobpilot_engage_task.xml /TN JobPilot-Engage
```

---

## 11. Não escopo desta v1

- Engajar em DMs ou notificações
- Compartilhar conteúdo próprio (publicar posts originais)
- Reagir além de "thumbs up" (celebrate, support, love, insightful, funny)
- Comentar em replies de outros comentários
- Comentar em posts próprios
- A/B testing de prompts
- Analytics dashboard separado
