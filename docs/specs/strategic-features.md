# Spec — Pacote de features estratégicas (SSI + operação)

> **Status: IMPLEMENTADO.** Reflete o código. Pontos DOM-dependentes não
> verificados ao vivo estão marcados ⚠️.

Conjunto de 9 features focadas em subir SSI e operar com menos atrito. Reusam
os padrões do projeto: trackers JSON atômicos (tmp→replace, chaves
week/month/day, hard cap), publish/approve-on-Telegram, browser lock
compartilhado, LLM via `get_eval_provider()` (qwen3:8b/Ollama).

## 1. Follow-up DM pós-conexão

Aceitou convite → DM curto via LLM → aprovação humana no Telegram → envio.

- **Geração precisa de browser** (lê conexões recentes), **envio também**
  (abre perfil + messaging). Geração via CLI/`/followup`; envio on-approval no
  bot runner. Espelha o publish-on-approval do autopost.
- `src/core/use_cases/followup_dm.py` — `FollowupDMGenerator.generate(name, headline)` + `validate_dm`.
- `src/core/use_cases/followup_tracker.py` — `FollowupTracker` (`followup_dms.json`): drafts (pending/approved/rejected/sent/skipped) + sent; dedupe por `profile_url` (nunca 2 DMs pra mesma pessoa); `counts_for_week`.
- `src/automation/pages/connections_page.py` — `ConnectionsPage.recent_connections(limit)` ⚠️ scrape best-effort de `/mynetwork/.../connections/`.
- `src/automation/pages/messaging_page.py` — `MessagingPage.send_dm(profile_url, text)` ⚠️ abre perfil → "Mensagem" → digita → envia.
- `src/automation/tasks/followup_manager.py` — `FollowupManager.scan()`.
- CLI `followup` + bot `/followup` (runner `launch_followup_scan`/`launch_followup_send`).
- Callbacks `followup_*` no `ConversationFlow` (approve/reject/edit/regen).

## 2. Human-in-loop no Telegram (engage)

O comentário gerado pela IA passa por aprovação antes de postar — sem rework
do engage por causa de DOM stale: a tarefa roda no runner e **bloqueia
aguardando** a decisão.

- `src/bot/approval.py` — `ApprovalGate`: `await request(kind, text, author)`
  manda botões e dá poll (`asyncio.sleep`) até o callback resolver; timeout →
  reject. Thread-safe (`Lock`) porque o callback chega na thread do polling e a
  tarefa roda na thread do runner. Decisões: approve / reject / edit (novo texto).
- `EngagementManager(comment_approver=...)`: `comment = await approver(comment, author)`; `None` ⇒ pula o comentário.
- Bot `/engage [n]` → `runner.launch_engage(review=True)` injeta o approver.
- Callbacks `engage_*` + step `engage_edit` no `ConversationFlow`.
- CLI `engage` (sem bot) roda automático (`comment_approver=None`).

## 3. Engage com alvo

Comentar na rede relevante (empresas-alvo) pesa mais no SSI que feed aleatório.

- `src/core/use_cases/engage_targets.py` — load/save (`engage_targets.json`) + `matches_target(author, text, targets)` (sem alvos ⇒ engage normal).
- `EngagementManager(targets=[...])` filtra candidatos antes do `is_relevant`.
- CLI `engage --target X --target Y [--save-targets]`; bot usa `load_targets()`.

## 4. Detecção de checkpoint/CAPTCHA

Página de verificação → alerta Telegram "resolve manual" + aborta limpo, em vez
de queimar o run.

- `src/automation/checkpoint.py` — `detect_checkpoint(page)` (URL `/checkpoint`,
  iframes recaptcha/hcaptcha, marcadores de texto PT/EN com body curto p/ evitar
  falso-positivo) + `ensure_not_blocked(page, label)` (alerta + `raise CheckpointError`).
- Plugado após navegação em: `FeedPage.goto`, `ConnectionManager`, `BaseApplicationManager`, `ConnectionsPage`, `MessagingPage`.

## 5. Dashboard TUI

`textual` (já dep) — view read-only ao vivo, sem abrir JSON.

- `src/interfaces/tui/stats.py` — `gather_stats()` (reusa `ReportRepository`/`MetricsCalculator`, sem browser).
- `src/interfaces/tui/dashboard.py` — `DashboardApp` (painéis candidaturas/engagement/autopost/SSI/metas; refresh 30s; `r`/`q`).
- CLI `dashboard`.

## 6. A/B test de comentário

Marca a variante de comentário usada; relatório mostra distribuição.

- `EngagementHandler.generate_comment(...) -> (texto|None, variant)` com 2 ângulos (`insight`/`pergunta`), escolha aleatória.
- `EngagedPostsTracker.mark_engaged(..., variant)` grava a variante.
- `MetricsCalculator.engagement` agrega `by_variant`; `ReportFormatter._engagement_block` renderiza "🧪 A/B comentário".
- ⚠️ Conversão real (qual variante gera mais resposta) precisa de tracking de respostas de recruiter — futuro.

## 7. Rotação de saved-searches

Lista de buscas roda em rodízio (mais cobertura).

- `src/core/use_cases/saved_searches.py` — `SavedSearches` (`saved_searches.json`): `add/list/remove/next(task)` round-robin com cursor por tarefa.
- CLI `searches {list|add|remove|next}`; `connect --rotate` consome `next("connect")`.

## 8. Export CSV

Dump dos JSONs para CSV (Excel/Sheets/Notion).

- `src/core/use_cases/exporter.py` — `export_applied_csv`/`export_rejected_csv` (UTF-8-BOM p/ Excel).
- CLI `export {applied|rejected|all} [--out]`. Notion/Sheets via API: futuro.

## 9. Meta semanal + alerta

Alvos semanais; relatório avisa o que está atrás.

- `src/core/use_cases/goals_tracker.py` — `GoalsTracker` (`goals.json`): `get/all/set` para `applications/connections/posts/comments` (defaults sensatos).
- `ReportBuilder._goals_progress` cruza com o realizado da semana; `ReportFormatter._goals_block` mostra barras + "⚠️ Atrás em".
- CLI `goals {show|set}`.

## 10. Visualizações do perfil (90d) — tendência + aceleração

Captura diária da contagem de "visualizações do perfil" (janela 90d) e análise:
não só "está subindo?" (1ª derivada = ritmo views/dia) mas "está **acelerando**?"
(2ª derivada = variação do ritmo entre janelas).

- `src/automation/pages/profile_views_page.py` — `ProfileViewsPage` raspa a página
  de analytics (PT+EN, número antes/depois do rótulo). ⚠️ selectors 2026 best-effort.
- `src/core/use_cases/profile_views_tracker.py` — `ProfileViewsTracker`: snapshot
  diário (upsert por data) + `analyze(window)` → `trend` (subindo/caindo/estável) e
  `pace` (acelerando/desacelerando/constante), com `rate_recent`/`rate_prior`/`accel`.
  Como o 90d é total rolante, a variação é normalizada por dia (tolera buracos).
- Captura plugada no fim do `engage` (best-effort, 1×/dia, espelha SSI).
- CLI `profile-views {show [--window N]|list}`.

## Persistence

Camada backend-swappable por `DATABASE_URL`: vazio = **JSON** (`.local/files/`,
default); setado = **Postgres** remoto. `KeyedRepo` (tipado) + `DocRepo` (kv JSONB)
cobrem os 14 trackers; CLI `db {check|init|migrate|status}`. Ver `docs/persistence.md`.

JSON novos (gitignored): `followup_dms.json`, `engage_targets.json`,
`saved_searches.json`, `goals.json`, `profile_views.json`.
`engaged_posts.json` ganhou o campo `variant`.

## Não-escopo / futuro

- Verificar `ConnectionsPage`/`MessagingPage`/composer contra DOM real do LinkedIn 2026.
- Tracking de respostas de recruiter (fecha o loop do A/B test).
- Export direto p/ Notion/Google Sheets (hoje só CSV).
- Agendamento próprio do follow-up/engage (hoje via bot ou run manual).
