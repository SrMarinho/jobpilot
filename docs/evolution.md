# Autoevolução

O JobPilot roda sozinho por Windows Scheduled Tasks. Quando o LinkedIn muda o
HTML, a falha é **silenciosa**: o resolver devolve `None`, o `except` genérico
engole, e o run "termina bem" fazendo nada. Ninguém percebe até olhar resultado
ruim dias depois.

O caso que originou este subsistema: `campo=invite modal` falhou **711 vezes em
15 dias** sem ninguém consertar. E o diagnóstico revelou algo pior que uma
quebra — os 711 avisos eram o **caminho de sucesso**. O LinkedIn 2026 envia
convite sem abrir modal, e `invitation_handler` confirmava o envio por
`pending_count()` três linhas depois do aviso. O código funcionava; o log
mentia.

Daí o princípio que organiza tudo: **o sistema precisa distinguir "nosso
selector apodreceu" de "a plataforma mudou o fluxo" de "a feature morreu"**.
Curar tudo é tão errado quanto curar nada.

## Os três laços

| Laço | Onde roda | Gate | Latência |
|---|---|---|---|
| **A. Cura in-run** | dentro do browser, DOM vivo | validação na própria página | segundos |
| **B. Patch autônomo** | drain horário, sem browser | caminhos → ruff → pytest → smoke | ~1h |
| **C. Diagnóstico** | drain, 1×/dia | classificação LLM → roteia pra A, B ou Telegram | 1 dia |

Promover um selector validado **não usa LLM**: editar `_INVITE_MODAL = [...]` é
regex numa `list[str]`. O `claude -p` fica só para o que não é mecânico
(`retire_feature`, `patch_bug`, `demote_log`). Menos graus de liberdade para um
LLM com permissão de escrita.

## Ligando (nada está ligado por default)

```bash
# .env — cada trava é independente, e a ordem é de risco crescente
EVOLVE_HEAL=true        # laço A: cura de selector no run
EVOLVE_ENABLED=true     # laço B: patch em worktree (sem push)
EVOLVE_PUSH=true        # ... e empurra a branch evolve/* pro GitHub
```

Comece com `EVOLVE_HEAL` sozinho. Ele não toca no código-fonte: o selector
aprendido vive no banco e o run segue. Só ligue `EVOLVE_ENABLED` depois de ver
no `config evolve queue` que as promoções enfileiradas fazem sentido.

**Antes de ligar `EVOLVE_PUSH`**: configure branch protection na master do
GitHub. A checagem `is_pushable` é a trava de dentro; branch protection é a
única que não depende do nosso código estar correto.

## Comandos

```bash
uv run main.py config evolve scan [--days 14 --all --diagnose --telegram]
uv run main.py config evolve incidents [--all]     # estado por assinatura
uv run main.py config evolve ignore <sig> [--days 30]
uv run main.py config evolve queue                 # o que a cura pediu
uv run main.py config evolve drain [--dry-run]     # executa um job
uv run main.py config evolve status                # orçamento e freios
uv run main.py config evolve pause [--off]         # kill switch
uv run main.py config evolve reset-cooldown
uv run main.py config selectors-check --heal       # melhor ambiente de cura
```

`config evolve scan` sem `--diagnose` só observa: nada age. É por onde começar.

## Como a cura decide

Todo campo de selector é declarado em `selector_registry.py` com intenção
semântica em português, escopo e — o item que sustenta a autonomia — `expect`:
a regex que o nome acessível do elemento tem que casar.

**Campo clicável sem `expect` é declarado incurável.** Um candidato alucinado
num campo clicável vai ser clicado de verdade, e no LinkedIn isso manda convite,
DM ou denúncia em nome do usuário. Contagem e visibilidade aprovariam o botão
"Denunciar"; só a regex reprova. `tests/test_selector_registry.py` cobra isso
campo por campo, então "clicar no escuro" não é um estado alcançável.

Validação na página viva, em ordem: regra de segurança → casa ≥1 → casa
≤`max_matches` → visível → habilitado e clicável → nome acessível bate `expect`.
**Nunca clica para validar** — um teste que age não é teste, é a ação.

### Guard rails da cura

A cura roda **com o lock do browser na mão**, e o lock tem teto de 600s que já
estourou. Por isso:

- 2 curas por run, 60s no total, 1 tentativa por campo por run
- cooldown de 24h por campo após falha; 3 falhas marcam incurável (segue
  reportando, para de gastar LLM)
- quota de 5/dia e 20/semana (`LIMIT_HEAL_DAY`), via o `RateLimiter` que já
  existe
- sob checkpoint/CAPTCHA a cura é pulada: o DOM não é a página real e a cura
  aprenderia lixo
- o gancho **nunca levanta** — falha vira log e o resolver segue pelo caminho
  que seguiria se esta feature não existisse

## O que o patch pode tocar

Denylist vence allowlist, sempre. Fora de alcance, com motivo:

| Caminho | Por quê |
|---|---|
| `.env*` | segredos e a URL do Postgres de produção |
| `.local/**` | sessão do Chrome e os XMLs do Agendador |
| `src/core/persistence/**` | o caminho até o banco de produção |
| `src/core/use_cases/evolve/**`, `src/automation/evolve/**` | os próprios guard rails |
| `.github/**` | o CI é o segundo par de olhos independente |
| `pyproject.toml`, `uv.lock` | dependência nova é decisão humana |
| `main.py`, `router.py`, `src/config/**`, `telegram.py` | a fiação, incluindo o canal de aviso |

Patch em task agendada (`.ps1`/`.bat`/`.xml`) é proibido em qualquer lugar: ou
não faz nada (precisa de re-import como admin) ou derruba todas as tasks em
silêncio.

**A ordem dos gates é substantiva**: caminhos primeiro, porque `pytest` importa
o código do patch — importar é executar.

> Buraco encontrado na verificação, e corrigido: `git status --porcelain`
> **esconde** arquivo que está no `.gitignore`, e `.env` está lá. O gate
> aprovou um worktree onde `.env` havia sido escrito, porque não o viu.
> Hoje a chamada usa `--ignored=matching -uall`. Se alguém remover essa flag,
> o gate volta a ficar cego — `tests/test_patcher_gates.py` trava o parser, mas
> a flag em si vive na chamada do git.

O agente (`claude -p`) roda sem `Bash`, `WebFetch` e `WebSearch`: não roda git,
não instala dependência, não sai pra rede. Todo git é feito em Python com argv
em lista, nunca string de shell com texto de LLM interpolado. O `.env` não entra
no worktree, e o ambiente do filho vai com `DATABASE_URL` **vazia** (não
ausente) — vazia é o que faz a persistência cair no JSON local.

## Freios do patch

- 2 patches/dia, 5/semana, US$ 1/dia (somado do JSON do `claude -p`)
- job morre em 2 tentativas
- 3 falhas de gate seguidas abrem cooldown de 24h **só da evolução** (o
  cooldown do `RateLimiter` bloquearia todos os runs agendados, e uma falha de
  patch não pode parar as candidaturas)
- anti-loop por `(assinatura, commit base)`: mesmo problema sobre o mesmo
  código é tentado **uma** vez, pra sempre
- patch é contado mesmo quando reprova — o custo do LLM já aconteceu
- `config evolve pause` desliga sem mexer no `.env`

Telegram em **toda** tentativa, sucesso ou falha. Silêncio não é estado
possível: um sistema que altera código sozinho e não conta não é autônomo, é
solto.

## Verificando sem esperar o LinkedIn quebrar

```bash
# 1. Observação pura, contra os logs de verdade
uv run main.py config evolve scan --dry-run --days 30

# 2. Injeção de falha: o campo perde os candidatos declarados e a cura dispara
#    de verdade, contra o DOM real
EVOLVE_FAULT_FIELD="linkedin job title" EVOLVE_HEAL=true \
  uv run main.py --headless config selectors-check --heal

# 3. Pipeline de patch com job sintético, sem push
DATABASE_URL="" EVOLVE_ENABLED=true EVOLVE_PUSH=false \
  uv run main.py config evolve drain
```

Rode as primeiras vezes com `DATABASE_URL=""`: tudo aterriza em
`.local/files/*.json` e nada toca produção.

## Estado persistido

Tudo `DocRepo` — zero DDL, porque `KeyedRepo` exigiria mexer no `_SCHEMA` e o
`DATABASE_URL` local aponta pra **produção**.

| Arquivo | Conteúdo |
|---|---|
| `selector_overrides.json` | selectors aprendidos, com hits/misses |
| `evolution_incidents.json` | estado por assinatura de falha |
| `evolution_queue.json` | fila de trabalho |
| `evolution_state.json` | contadores, custo, cooldown, pausa |
| `evolution_patches/<id>.json` | diff e saída dos gates de cada tentativa |

## Limites conhecidos

- **Master não se cura sozinha.** As branches `evolve/*` não são mergeadas
  automaticamente (`EVOLVE_AUTOMERGE` não existe ainda). Enquanto não forem, o
  banco é a fonte de verdade e o código-fonte fica atrás. Revise as branches.
- **`pytest` no worktree executa código de LLM.** A denylist antes do pytest
  reduz, não elimina. O raio de dano é limitado por: sem `.env`, sem
  `DATABASE_URL`, sem Bash pro agente.
- **Nem todo campo é alcançável.** `get_connect_btn`, `feed_page` e
  `feed_composer_page` montam os seletores em variável local, não em constante
  de módulo — não há o que sobrescrever nem promover. Documentado em
  `UNREACHABLE`, no registry.
- **Campo do canário ≠ campo do resolver.** O canário nomeia `job_title`; o
  resolver, `linkedin job title`. A cura funciona (ela passa pelo resolver), mas
  o incidente do canário não se liga ao registry.
- **Assinatura por hash perde parafrase.** Duas redações da mesma falha viram
  dois incidentes. `merge_by_field` cobre o caso em que o campo é citado; fora
  dele, não.
- **`ExecutionTimeLimit` do drain foi pra `PT30M`.** Se você reimportar um XML
  antigo, o Agendador volta a cortar o patch em 10 minutos.
