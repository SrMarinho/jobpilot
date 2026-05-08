# Configuration

## Environment variables (`.env`)

```env
# Chrome visibility: FALSE = visible, TRUE = hidden
HEADLESS=FALSE

# Telegram (optional — required for bot mode and notifications)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_channel_id    # channel/group for notifications
TELEGRAM_ADMIN_ID=your_personal_id  # your personal chat ID for commands

# LLM provider for form Q&A
LLM_PROVIDER=claude                          # "claude" or "langchain"
CLAUDE_MODEL=claude-haiku-4-5-20251001
LANGCHAIN_MODEL=llama3.1:8b                  # recommended local model
LANGCHAIN_BASE_URL=http://localhost:11434

# Separate provider for job evaluation (fallback to LLM_PROVIDER if not set)
LLM_PROVIDER_EVAL=langchain
LANGCHAIN_MODEL_EVAL=deepseek-r1:14b         # smarter model for evaluation
```

### LLM provider options

| Option | Description | Requires |
|--------|-------------|----------|
| `claude` | Uses claude-agent-sdk (Claude Code CLI) | Claude Pro plan, `claude` CLI installed |
| `langchain` | Uses Ollama (local LLM) | Ollama running, model pulled |

### Model recommendations

| Use case | Claude model | Ollama model |
|----------|-------------|-------------|
| Form Q&A (cheap/fast) | `claude-haiku-4-5-20251001` | `llama3.2:3b` |
| Job evaluation (smart) | `claude-sonnet-4-20250514` | `deepseek-r1:14b` |

### Getting Telegram IDs

Send any message to your bot, then open:
```
https://api.telegram.org/bot<TOKEN>/getUpdates
```
Your `chat.id` appears in the response. Use it for `TELEGRAM_ADMIN_ID`.

For channel notifications, create a channel, add the bot as admin, and forward a message from the channel to `@RawDataBot` to get the channel ID.

### Chrome profile

Login sessions persist in `bot_profile/` (gitignored). Each site's cookies and local storage are saved. If Chrome updates, clear `bot_profile/` and re-login.

### Provider override

Per-run overrides via CLI flags take priority over `.env`:

```bash
# Override eval to use Claude for this run
uv run main.py apply --keywords "python" --eval-provider claude --eval-model claude-sonnet-4-20250514
```

Persistent changes use `provider set`:

```bash
uv run main.py provider set eval langchain --model llama3.1:8b
```
