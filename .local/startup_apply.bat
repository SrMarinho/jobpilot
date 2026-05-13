@echo off
cd /d "F:\Documentos\Projetos\Code\jobpilot"
"C:\Users\Sr. Marinho\.local\bin\uv" run main.py apply ^
  --keywords "desenvolvedor backend" ^
  --site linkedin ^
  --date-posted 24h ^
  --resume ".\\.local\\Matheus Marinho - Curriculo.pdf" ^
  --preferences "Python ou Node.js backend, obrigatoriamente remoto, apenas vagas em português, nível junior ou pleno" ^
  --level junior --level pleno ^
  --max-pages 2 ^
  --llm-provider langchain ^
  --eval-provider langchain ^
  --headless ^
  --no-save
