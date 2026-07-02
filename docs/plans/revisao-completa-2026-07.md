# Plano — Revisão completa: código, robustez, docs e features

> Progresso: marque `[x]` conforme os itens forem concluídos.

## Contexto

Revisão completa do projeto (docs lidas por inteiro + 3 varreduras de código: core,
automation/bot/cli, persistence/infra). Projeto funcional e bem arquitetado em
camadas, mas acumulou: 1 bug real (Glassdoor), 1 falha de segurança no bot, drift
severo de documentação (CLAUDE.md/README descrevem CLI flat que não existe mais),
~250 linhas de dead code, duplicação sistêmica (handlers, trackers, telegram,
prompts), zero testes e robustez frágil (sem retry em rede/LLM, exceptions
engolidas).

Decisões:
- **Glassdoor**: NÃO consertar — só documentar como quebrado/não-suportado.
- **Escopo**: código + features novas.
- **Testes**: sim, pytest para módulos puros.

---

## FASE 1 — Segurança e bugs (crítico, pequeno)

- [ ] 1.1 Admin gating do bot Telegram (segurança). `src/bot/telegram_bot.py:48-51`
      confere `chat_id` em mensagens (não o autor); callbacks conferem `from.id`
      (linha 42). Com `TELEGRAM_ADMIN_ID` ausente (fallback pra `TELEGRAM_CHAT_ID`,
      `client.py:18-20`), qualquer membro do grupo dispara `/apply`, `/stop`,
      `/reiniciar` (`os.execv`, `router.py:99-102`). Fix: checar
      `msg["from"]["id"] == admin_id` também nas mensagens.
- [ ] 1.2 Loop de polling do bot pode morrer/virar busy-loop.
      `telegram_bot.py:33-36` sem try/except no dispatch; `client.py:108` retorna
      `[]` imediato em erro de rede. Fix: try/except + backoff curto (~5s).
- [ ] 1.3 Glassdoor quebrado — só documentar (não corrigir).
      `GlassdoorJobsPage` não implementa `get_card_job_url`/`get_company_name`
      (`base.py:16-34`) → `TypeError` ao instanciar via `--site glassdoor`.
      Nota "⚠️ Glassdoor quebrado/não-suportado" em cli.md, architecture.md,
      README.md, CLAUDE.md.
- [ ] 1.4 `settings.py:26` `files_dir.mkdir(exist_ok=True)` sem `parents=True`.

---

## FASE 2 — Documentação (drift severo, só texto)

- [ ] 2.1 Regenerar CLAUDE.md: CLI flat obsoleto → árvore agrupada real
      (`router.py:36-98`); `metrics`→`profile capture`; `profile-views`→
      `profile views`; `db`→`config db` (incluir `pull`); "main.py 9 lines"→28;
      layout de `cli/` sem `hired/`,`telegram_topics/`,`profile/*`,`provider/key`;
      `report/` cita `metrics.py`/`service.py` inexistentes; "14 trackers"
      defasado (~34 use_cases); remover menção a `evaluate` sync deprecated.
- [ ] 2.2 Atualizar README.md — exemplos de comando errados (flat) → agrupados;
      adicionar `config db pull`.
- [ ] 2.3 docs/architecture.md: `monthly_report.py`→package `report/`; `db pull`;
      nota Glassdoor.
- [ ] 2.4 docs/cli.md: adicionar `config db pull`; nota Glassdoor.
- [ ] 2.5 docs/persistence.md: documentar `db pull` (Postgres→JSON local).
- [ ] 2.6 docs/scheduled-tasks.md: cobrir 6+ tasks reais (engage/autopost/drain
      além de apply/connect/report/hired); exemplos `.bat` flat → agrupados.
- [ ] 2.7 Help do `router.py:95`: incluir `pull`.
- [ ] 2.8 .gitignore: whitelistar `startup_hired.*`, `jobpilot_hired_task.xml`,
      `startup_autopost.*`, `jobpilot_autopost_task.xml`, `startup_drain.bat`,
      `reimport_tasks.ps1`; corrigir typos (`.env.`, `Thumbs.db.env`, `.env`×3).

---

## FASE 3 — Dead code e higiene (baixo risco)

- [ ] 3.1 `job_application_handler.py`: remover ~12 métodos privados nunca
      chamados (~250 linhas): `_fill_react_select`, `_find_question_in_modal`,
      `_extract_modal_options`, `_handle_radio_in_scope`, `scroll_to_review`,
      `_handle_react_select`, `_has_form_errors`, `_close_modal`,
      `_check_required_after_close`, `_fill_errors`, `_has_discard_modal`,
      `_close_discard` + const `_REACT_SELECT_SETTER`.
- [ ] 3.2 Deletar `src/config/logging.py` (dead, duplica settings.py).
- [ ] 3.3 Deletar `.pyc` órfão `cli/metrics/__pycache__/`.
- [ ] 3.4 Renomear `src/automation/tasks/test_apply.py` (prefixo `test_` colide
      com pytest); trocar 5 `print()` por `logger`.
- [ ] 3.5 Confirmar e deletar `scripts/migrate_local_to_db.py` (obsoleto).
- [ ] 3.6 Confirmar e remover `runner.py:291-306 _capture_ssi` se não chamado.
- [ ] 3.7 `browser.py:219`: `logger.critical`→`logger.error`.

---

## FASE 4 — Robustez (médio esforço)

- [ ] 4.1 `utils/telegram.py`: `html.escape()` no conteúdo dinâmico; retry com
      backoff (2-3x) + tratamento HTTP 429; checar `resp.ok` antes de `.json()`.
- [ ] 4.2 Helper `goto_with_retry(page, url, retries=2)` — usar em
      `base_application_manager.py:141,303`, `connection_manager.py:41`,
      `feed_page.py:89`.
- [ ] 4.3 Retry (1-2x + backoff) em `LLMProvider.complete`.
- [ ] 4.4 `KeyedRepo`: capturar erro de conexão com mensagem clara; avaliar
      allowlist de colunas por tabela (mitiga injeção via dict keys,
      `keyed_repo.py:45-74`).
- [ ] 4.5 Exceptions engolidas seletivas: `submit_easy_apply` (retorna True com
      falha parcial), `evaluate_batch` parse silencioso, warmup que deixa
      provider quebrado passar.

---

## FASE 5 — Refactors de duplicação (maior esforço)

- [ ] 5.1 Form handlers: extrair `FormFillerBase`/`form_filling.py` comum entre
      `job_application_handler.py` e `indeed_application_handler.py`; mover
      ambos para `src/automation/` (dependem de Playwright).
- [ ] 5.2 `BaseTracker`: unificar `_FILES_DIR`/`_HARD_CAP`/chaves
      week-month-day/`is_db_enabled()` de ~10 trackers; unificar
      `counts_for_week`/`counts_for_month` (idênticos em
      `engaged_posts_tracker.py:89-129`).
- [ ] 5.3 Unificar `bot/client.py` e `utils/telegram.py` (payload/keyboard/topic
      duplicados) — retry/escape da 4.1 entra uma vez só.
- [ ] 5.4 `LLMGeneratorBase` + `strip_think()` único para
      `engagement_handler`/`post_drafter`/`followup_dm`.
- [ ] 5.5 Helpers menores: espera de load duplicada
      (`base_application_manager.py:389-412` ≡ `connection_manager.py:56-79`);
      constantes de truncamento/timeout; modelo Claude default duplicado
      (`llm_provider.py:44,111`); trackers usarem `settings.files_dir`; builder
      comum pros prompts `evaluate_async`/`evaluate_batch`.

---

## FASE 6 — Testes (pytest, módulos puros)

- [ ] 6.1 Adicionar `pytest` a `[dependency-groups] dev`; criar `tests/`;
      `[tool.pytest.ini_options]` no pyproject.
- [ ] 6.2 Testes `url_builder.py` (100% puro).
- [ ] 6.3 Testes `content_filters.py` (blacklist/grounding/foreign-tech).
- [ ] 6.4 Testes `post_drafter.validate_draft` + `followup_dm.validate_dm`.
- [ ] 6.5 Testes `hired_posts.py` (parsing puro).
- [ ] 6.6 Testes `report/period.py` + `builder`/`formatter`.
- [ ] 6.7 Testes trackers com repo fake (`goals_tracker`, `saved_searches`,
      `posted_tracker`).

## FASE 6b — Higiene pyproject/tooling

- [ ] 6b.1 Mover `ruff` pra dev deps; remover `setuptools` não usado.
- [ ] 6b.2 Adicionar `[tool.ruff]` versionado.
- [ ] 6b.3 `description` placeholder → real.
- [ ] 6b.4 Alinhar rev do ruff em `.pre-commit-config.yaml` com pyproject.

---

## FASE 7 — Features novas (backlog, sob demanda)

- [ ] 7.1 Tracking de respostas de recruiter (fecha loop A/B comentário + DM).
- [ ] 7.2 Lock de escrita JSON (`filelock`) em `persistence.py`/`doc_repo._write_local`.
- [ ] 7.3 Screenshots com timestamp + rotação.
- [ ] 7.4 `insights report --compare` (delta semana atual vs anterior).
- [ ] 7.5 Health check `doctor` (LinkedIn/Ollama/Telegram/DB/resume/tasks).
- [ ] 7.6 Export Notion/Sheets via API.
- [ ] 7.7 Auto-resposta a comentários nos próprios posts (autopost).

---

## Ordem de commits (Conventional Commits PT-BR, sem co-author)

1. `fix(bot): admin gating por autor + polling resiliente` (1.1+1.2)
2. `fix(config): mkdir parents em files_dir` (1.4)
3. `docs: sincroniza CLAUDE.md/README/docs com CLI agrupado + db pull + glassdoor quebrado` (Fase 2)
4. `chore: remove dead code (handlers, config/logging, pyc órfão, scripts obsoletos)` (Fase 3)
5. `fix(telegram): escape HTML + retry/429` / `fix(automation): retry em goto` / `fix(persistence): erros claros no KeyedRepo` (Fase 4)
6. Refactors da Fase 5, um por tema (`refactor(handlers)`, `refactor(trackers)`, `refactor(telegram)`, `refactor(llm)`)
7. `test: suíte pytest módulos puros` + `chore: higiene pyproject/tooling` (Fase 6)

## Verificação

- `uv run ruff check` limpo após cada fase.
- Fase 1: mensagem de conta não-admin em grupo → ignorada.
- Fase 4: forçar erro de rede (Telegram/goto) e ver retry no log.
- Fase 5: smoke `jobs apply --no-submit --max-applications 1` e
  `content autopost --dry-run --no-telegram` (só nos refactors grandes).
- Fase 6: `uv run pytest` verde na criação.
