# JobPilot Documentation

## Uso

- [CLI Reference](cli.md) — All commands, flags, and usage examples
- [Telegram Bot](bot.md) — Comandos, modelo de tarefas, aprovação human-in-loop
- [Configuration](configuration.md) — `.env` setup, LLM providers, Chrome profile, Telegram
- [Search URL Builder](search-builder.md) — CLI flags to URL mapping for LinkedIn, Indeed, Glassdoor
- [Scheduled Tasks](scheduled-tasks.md) — Windows Task Scheduler automation setup

## Interno

- [Architecture](architecture.md) — Layer stack, request flow, key components, adding new job boards
- [Persistence](persistence.md) — Backend JSON/Postgres, `KeyedRepo` e `DocRepo`
- [Browser lock](browser-lock.md) — Como as sessões Chrome são serializadas entre processos

## Specs e planos

- [specs/](specs/) — Especificações de features (autopost, engage, persistence, estratégico)
- [plans/](plans/) — Planos de revisão e refactor
