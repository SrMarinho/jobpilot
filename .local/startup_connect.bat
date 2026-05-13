@echo off
cd /d "F:\Documentos\Projetos\Code\jobpilot"
"C:\Users\Sr. Marinho\.local\bin\uv" run main.py connect ^
  --keywords "tech recruiter" ^
  --network S ^
  --scheduled ^
  --headless
