@echo off
set PYTHONIOENCODING=utf-8
rem Provider e modelo andam juntos: --llm-provider langchain sem fixar o
rem modelo cai no .env, e um model id da Anthropic no backend Ollama da 404
rem em todo batch de avaliacao (foi assim por 41 dias).
set LANGCHAIN_BACKEND=deepseek
set LANGCHAIN_BACKEND_EVAL=deepseek
set LANGCHAIN_MODEL=deepseek-v4-flash
set LANGCHAIN_MODEL_EVAL=deepseek-v4-flash
cd /d "F:\Documentos\Projetos\Code\jobpilot"

echo === BACKEND ===
"C:\Users\Sr. Marinho\.local\bin\uv" run main.py --headless jobs apply ^
  --keywords "desenvolvedor" --keywords "backend" ^
  --site linkedin ^
  --date-posted 24h ^
  --resume ".\.local\\Matheus Marinho - Curriculo.pdf" ^
  --preferences "Python ou Node.js backend, obrigatoriamente remoto, apenas vagas em portugues, nivel junior ou pleno" ^
  --level junior --level pleno ^
  --max-pages 2 ^
  --llm-provider langchain ^
  --eval-provider langchain ^
  --no-save

echo === FULLSTACK ===
"C:\Users\Sr. Marinho\.local\bin\uv" run main.py --headless jobs apply ^
  --keywords "desenvolvedor" --keywords "fullstack" ^
  --site linkedin ^
  --date-posted 24h ^
  --resume ".\.local\\Matheus Marinho - Curriculo.pdf" ^
  --preferences "Python ou Node.js backend, obrigatoriamente remoto, apenas vagas em portugues, nivel junior ou pleno" ^
  --level junior --level pleno ^
  --max-pages 2 ^
  --llm-provider langchain ^
  --eval-provider langchain ^
  --no-save
