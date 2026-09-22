@echo off
cd /d "F:\Documentos\Projetos\Code\jobpilot"
set PYTHONIOENCODING=utf-8
REM Drena aprovacoes/rejeicoes do Telegram p/ o banco (sem publicar, sem browser).
"C:\Users\Sr. Marinho\.local\bin\uv" run main.py content autopost --drain

REM ── Autoevolucao ────────────────────────────────────────────────────────────
REM Entra nesta task, e nao numa nova, porque e a unica que roda de hora em
REM hora e NAO usa browser: patch precisa de minutos (LLM + ruff + pytest +
REM smoke) e nao pode disputar o lock com os runs agendados.
REM
REM ATENCAO: o ExecutionTimeLimit do XML foi de PT10M para PT30M por causa
REM disto. Se voce reimportar uma versao antiga do XML, o Agendador corta o
REM patch no meio e sobra worktree orfao (o drain limpa no inicio, mas o
REM trabalho e perdido).
REM
REM Desligado por default: sem EVOLVE_ENABLED=true no .env o drain abaixo sai
REM em dois segundos dizendo que nao esta autorizado.
"C:\Users\Sr. Marinho\.local\bin\uv" run main.py config evolve drain

REM Varredura de log 1x/dia sai barata aqui: o proprio comando trava a parte
REM de LLM por dia, entao rodar de hora em hora nao multiplica custo.
"C:\Users\Sr. Marinho\.local\bin\uv" run main.py config evolve scan --scheduled --telegram --once-a-day
