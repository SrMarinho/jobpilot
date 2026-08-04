schtasks /delete /tn "JobPilot Apply" /f
schtasks /delete /tn "JobPilot Connect" /f
schtasks /delete /tn "JobPilot Report" /f
schtasks /delete /tn "JobPilot Hired" /f

schtasks /create /xml "F:\Documentos\Projetos\Code\jobpilot\.local\jobpilot_task.xml" /tn "JobPilot Apply"
schtasks /create /xml "F:\Documentos\Projetos\Code\jobpilot\.local\jobpilot_connect_task.xml" /tn "JobPilot Connect"
schtasks /create /xml "F:\Documentos\Projetos\Code\jobpilot\.local\jobpilot_report_task.xml" /tn "JobPilot Report"
schtasks /create /xml "F:\Documentos\Projetos\Code\jobpilot\.local\jobpilot_hired_task.xml" /tn "JobPilot Hired"
