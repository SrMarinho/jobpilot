@echo off
set PYTHONIOENCODING=utf-8
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
