@echo off
set PYTHONIOENCODING=utf-8
cd /d "F:\Documentos\Projetos\Code\jobpilot"
"C:\Users\Sr. Marinho\.local\bin\uv" run main.py --headless connect ^
  --keywords "tech recruiter" ^
  --network S ^
  --scheduled
