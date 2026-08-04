# Telegram bot

Controle remoto do JobPilot: dispara as mesmas tarefas da CLI e aprova conteúdo
gerado por IA antes de publicar.

```bash
uv run main.py bot
```

Requer `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` no `.env`. `TELEGRAM_ADMIN_ID`
é opcional (vazio => usa o chat principal) e define quem pode dar comandos.

## Comandos

| Comando | O que faz |
|---------|-----------|
| `/connect` | Abre o formulário de conexões (multi-etapas) e dispara |
| `/apply <url>` | Candidata a partir de uma busca |
| `/engage` | Engaja no feed, pedindo aprovação de cada comentário |
| `/autopost` | Gera rascunho de post autoral |
| `/autopost_topic <tema>` | Rascunho com tema definido |
| `/autopost_format` | Escolhe o formato do post |
| `/autopost_list` | Últimos posts + rascunhos pendentes |
| `/followup` | Busca conexões novas e gera DMs pra aprovar |
| `/resume` | Atualiza o currículo (envie o PDF em seguida) |
| `/status` | Diz se tem tarefa rodando |
| `/stop` | Sinaliza parada da tarefa atual |
| `/ping` | Verifica se o bot está vivo |
| `/reiniciar` | Reinicia o processo do bot |
| `/help` | Lista tudo |

## Arquitetura

Cinco peças, cada uma com uma responsabilidade (`src/bot/`):

| Módulo | Papel |
|--------|-------|
| `client.py` | Transporte HTTP puro. Só ele conhece `requests` e a URL da Bot API |
| `router.py` | Roteia slash commands. Sem HTTP, sem browser |
| `conversation.py` | Diálogos com estado (formulário de connect, upload de currículo) |
| `runner.py` | Executa as tarefas de browser em thread, uma por vez |
| `approval.py` | Human-in-loop: segura a tarefa até você aprovar o texto |
| `telegram_bot.py` | Orquestrador: liga as peças e roda o long-poll |

```
Telegram → TelegramClient.get_updates()
           → TelegramBot._dispatch()
              ├── callback de botão → ConversationFlow.handle_callback()
              ├── texto em diálogo  → ConversationFlow.handle_text()
              └── /comando          → UpdateRouter.handle_command()
                                        → BrowserTaskRunner.launch_*()
```

## Modelo de tarefas

**Uma tarefa de browser por vez.** `BrowserTaskRunner.is_busy()` recusa uma nova
enquanto a anterior vive; `/stop` sinaliza um `threading.Event` que os managers
checam cooperativamente.

Cada tarefa roda numa thread com seu próprio event loop e adquire o
[browser lock](browser-lock.md) — o mesmo que serializa contra as tarefas
agendadas e a CLI. Isso significa que uma tarefa pode ficar **na fila** por até
1h enquanto `is_busy()` já é verdadeiro.

Geração de rascunho de post não abre browser (é só LLM), então usa
`_spawn_detached` e não ocupa o slot.

Erros são reportados no Telegram e logados com traceback. Checkpoint do LinkedIn
tem mensagem própria — não vira "erro genérico".

## Human-in-loop (ApprovalGate)

O engage e o follow-up não publicam nada sem aprovação.

O problema que o gate resolve: a tarefa roda numa thread com seu próprio event
loop, mas o polling do Telegram roda na thread principal. O gate liga os dois —
a tarefa manda os botões e dá `await` num poll; o callback do Telegram resolve a
decisão num dict protegido por `threading.Lock`.

Decisões: **aprovar** (usa o texto), **rejeitar** (pula), **editar** (espera você
mandar outro texto). Sem resposta em 10 minutos, trata como rejeição — pra não
deixar o run travado indefinidamente segurando o browser lock.

O autopost usa um caminho diferente e assíncrono: o rascunho fica `pending` no
banco, a aprovação chega depois (`content autopost --drain` lê as respostas via
`getUpdates` com offset persistido) e a publicação é um passo separado. Assim o
post não depende do bot estar de pé no momento da aprovação.

## Limitações conhecidas

- `is_busy()` + `_spawn()` não são atômicos. Na prática não dá corrida porque o
  loop de polling é single-thread, mas não há mutex garantindo isso.
- Uma tarefa esperando na fila do browser lock aparece como "rodando" pro
  `/status`, sem indicar que ainda não começou.
- O bot não consulta as quotas diárias/semanais que o modo `--scheduled` da CLI
  respeita — um `/connect` pelo Telegram ignora esses limites.
