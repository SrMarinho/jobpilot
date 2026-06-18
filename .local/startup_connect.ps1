$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location 'F:\Documentos\Projetos\Code\jobpilot'

$Url = 'https://www.linkedin.com/search/results/people/?keywords=%28Desenvolvedor+OR+%22Software+Engineer%22+OR+Programador%29&network=%5B%22S%22%5D'

& 'C:\Users\Sr. Marinho\.local\bin\uv' run main.py --headless connect --url $Url --scheduled
