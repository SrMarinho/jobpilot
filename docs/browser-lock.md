# Browser lock

O invariante mais sutil do projeto: **uma única sessão Chrome pode usar o perfil
`.local/bot_profile` por vez**, entre processos.

Isso importa porque as tarefas agendadas disparam todas no logon, o bot do
Telegram pode estar rodando ao mesmo tempo, e você pode chamar um comando na mão.
Sem a fila, uma segunda sessão colidiria com o Chrome já aberto e morreria — ou
pior, corromperia o perfil e derrubaria as sessões logadas.

## Como funciona

`src/interfaces/cli/browser.py` implementa a fila com `filelock` sobre
`.local/bot_profile.lock`:

```
acquire_browser_lock(label)
  → tenta adquirir sem bloquear
  → ocupado? dorme 5s e tenta de novo (log a cada 30s)
  → desiste depois de 1h na fila (RuntimeError)
```

Duas escolhas deliberadas:

- **Poll assíncrono em vez de `lock.acquire(timeout=...)`** — o `await asyncio.sleep`
  mantém o event loop responsivo enquanto espera.
- **Lock de sistema operacional** — se o processo que segura o lock morre, o SO
  libera sozinho. Não há lock órfão de processo morto.

## Contrato

Quem adquire **tem** que liberar em `finally`:

```python
lock = await acquire_browser_lock("minha-tarefa")
try:
    ...
finally:
    _release_browser_lock(lock, "minha-tarefa")
```

Na prática você não escreve isso à mão — os dois pontos de entrada já cuidam:

| Caminho | Entrada | Onde |
|---------|---------|------|
| CLI | `run_browser_task(ctx, nome, work)` | `src/interfaces/cli/browser.py` |
| Bot | `BrowserTaskRunner._with_browser(label, work, ...)` | `src/bot/runner.py` |

Ambos garantem lock adquirido/liberado, contexto Chrome sempre fechado e
`CheckpointError` tratado como caso próprio (não como crash genérico).

## Locks órfãos do Chrome

`_clear_chrome_locks()` apaga `SingletonLock`/`SingletonCookie`/`SingletonSocket`
do perfil antes de subir o Chrome. É seguro apagar incondicionalmente **porque o
lock da aplicação já foi adquirido** — se chegamos aqui, nenhuma outra instância
do JobPilot está usando o perfil, então qualquer singleton presente é resto de um
processo que morreu.

Essa ordem é o ponto frágil: `create_context()` chama `_clear_chrome_locks()`, e
só é correto chamá-la **depois** de `acquire_browser_lock()`. Use sempre um dos
dois pontos de entrada acima em vez de chamar `create_context` direto.

## Perfil compartilhado entre sites

`.local/bot_profile` é o mesmo perfil Chrome para LinkedIn, Glassdoor e Indeed.
Consequência prática: `logout <site>` limpa só os cookies dos domínios daquele
site — limpar tudo derrubaria as sessões dos outros dois.

## Sintomas

| Sintoma | Causa provável |
|---------|----------------|
| `"Browser ocupado por outra instancia. X na fila"` | Normal — outra sessão está rodando. Ela espera. |
| `"Espera de browser lock excedeu 3600s"` | Um run travou segurando o lock. Verifique se sobrou Chrome aberto. |
| `run_login` nunca termina | Por design espera você fechar o Chrome; enquanto isso o lock fica preso e a fila não anda. |
