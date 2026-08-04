@echo off
cd /d "F:\Documentos\Projetos\Code\jobpilot"
set PYTHONIOENCODING=utf-8
REM Drena aprovacoes/rejeicoes do Telegram p/ o banco (sem publicar, sem browser).
"C:\Users\Sr. Marinho\.local\bin\uv" run main.py content autopost --drain
