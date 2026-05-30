from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
)
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY

PRIMARY = HexColor("#1a365d")
SECONDARY = HexColor("#2d3748")
ACCENT = HexColor("#3182ce")
TEXT = HexColor("#2d3748")
LIGHT = HexColor("#718096")

doc = SimpleDocTemplate(
    ".local/Matheus Marinho - Curriculo.pdf",
    pagesize=A4,
    rightMargin=0.5 * inch,
    leftMargin=0.5 * inch,
    topMargin=0.4 * inch,
    bottomMargin=0.4 * inch,
)

styles = getSampleStyleSheet()

name_style = ParagraphStyle(
    "Name",
    parent=styles["Heading1"],
    fontSize=22,
    textColor=PRIMARY,
    spaceAfter=2,
    fontName="Helvetica-Bold",
    alignment=TA_LEFT,
    leading=24,
)
job_title_header = ParagraphStyle(
    "JTH",
    parent=styles["Normal"],
    fontSize=12,
    textColor=ACCENT,
    spaceAfter=4,
    fontName="Helvetica-Bold",
)
contact_style = ParagraphStyle(
    "Contact",
    parent=styles["Normal"],
    fontSize=9,
    textColor=LIGHT,
    spaceAfter=10,
    fontName="Helvetica",
)
section_heading = ParagraphStyle(
    "SH",
    parent=styles["Heading2"],
    fontSize=11,
    textColor=PRIMARY,
    spaceAfter=4,
    spaceBefore=10,
    fontName="Helvetica-Bold",
    leading=13,
)
summary_style = ParagraphStyle(
    "Summary",
    parent=styles["BodyText"],
    fontSize=9.5,
    textColor=TEXT,
    spaceAfter=6,
    leading=12.5,
    fontName="Helvetica",
    alignment=TA_JUSTIFY,
)
job_position_style = ParagraphStyle(
    "JP",
    parent=styles["Normal"],
    fontSize=10.5,
    textColor=SECONDARY,
    spaceAfter=1,
    fontName="Helvetica-Bold",
)
company_period_style = ParagraphStyle(
    "CP",
    parent=styles["Normal"],
    fontSize=9,
    textColor=LIGHT,
    spaceAfter=3,
    fontName="Helvetica-Oblique",
)
bullet_style = ParagraphStyle(
    "Bullet",
    parent=styles["BodyText"],
    fontSize=9,
    textColor=TEXT,
    spaceAfter=2,
    leading=12,
    fontName="Helvetica",
    leftIndent=12,
    bulletIndent=2,
)
project_name_style = ParagraphStyle(
    "PN",
    parent=styles["Normal"],
    fontSize=10,
    textColor=SECONDARY,
    spaceAfter=1,
    fontName="Helvetica-Bold",
)
project_meta_style = ParagraphStyle(
    "PM",
    parent=styles["Normal"],
    fontSize=8.5,
    textColor=LIGHT,
    spaceAfter=2,
    fontName="Helvetica-Oblique",
)
skill_label_style = ParagraphStyle(
    "SL",
    parent=styles["Normal"],
    fontSize=9,
    textColor=PRIMARY,
    fontName="Helvetica-Bold",
    leading=12,
)
skill_value_style = ParagraphStyle(
    "SV",
    parent=styles["Normal"],
    fontSize=9,
    textColor=TEXT,
    fontName="Helvetica",
    leading=12,
)
edu_style = ParagraphStyle(
    "Edu",
    parent=styles["Normal"],
    fontSize=9.5,
    textColor=TEXT,
    spaceAfter=3,
    fontName="Helvetica",
    leading=12,
)

content = []

content.append(Paragraph("MATHEUS MARINHO", name_style))
content.append(
    Paragraph("Desenvolvedor Full-Stack | Python &amp; TypeScript", job_title_header)
)
content.append(
    Paragraph(
        "Teresina, PI &nbsp;&bull;&nbsp; (86) 98102-2333 &nbsp;&bull;&nbsp; temarinho76@gmail.com &nbsp;&bull;&nbsp; github.com/SrMarinho",
        contact_style,
    )
)
content.append(
    HRFlowable(width="100%", thickness=1.5, color=PRIMARY, spaceBefore=0, spaceAfter=8)
)

content.append(Paragraph("EXPERI&Ecirc;NCIA PROFISSIONAL", section_heading))
content.append(
    HRFlowable(width="100%", thickness=0.5, color=LIGHT, spaceBefore=0, spaceAfter=4)
)
content.append(Paragraph("Desenvolvedor Full-Stack Pleno", job_position_style))
content.append(
    Paragraph(
        "Nazaria - Distribuidora Farmac&ecirc;utica &nbsp;|&nbsp; Setembro 2022 - Presente",
        company_period_style,
    )
)

highlights = [
    "Desenvolvi e mantenho o <b>DataReplicator</b>, ferramenta ETL que replica mais de <b>130 entidades</b> entre SQL Server, Oracle e PostgreSQL com processamento paralelo (multi-threading), lotes de at&eacute; 50.000 linhas por ciclo e sincroniza&ccedil;&atilde;o incremental",
    "Criei o <b>Omniquery</b>, ferramenta ETL em Python que unifica consultas SQL em m&uacute;ltiplas bases heterog&ecirc;neas (MSSQL, Oracle, PostgreSQL) atrav&eacute;s do DuckDB, eliminando silos de dados nos pipelines da empresa",
    "Implementei bot Telegram para monitoramento remoto de jobs ETL com notifica&ccedil;&otilde;es autom&aacute;ticas de erro, reduzindo tempo de resposta a falhas",
    "Constru&iacute; automa&ccedil;&otilde;es RPA para extra&ccedil;&atilde;o de dados de sistemas internos (e-Docs, Procfit), eliminando trabalho manual repetitivo e erros de transcri&ccedil;&atilde;o",
    "Arquitetei e implementei APIs RESTful em Node.js e Python integradas com interfaces React/TypeScript e Vue.js para sistemas internos de gest&atilde;o",
    "Otimizei queries SQL complexas com CTEs, Window Functions e estrat&eacute;gias de indexa&ccedil;&atilde;o, melhorando performance de relat&oacute;rios cr&iacute;ticos",
    "Apliquei princ&iacute;pios SOLID, Design Patterns e TDD em projetos de longa dura&ccedil;&atilde;o, garantindo manutenibilidade e qualidade",
]
for h in highlights:
    content.append(Paragraph("&bull; " + h, bullet_style))
content.append(Spacer(1, 0.05 * inch))

content.append(Paragraph("PROJETOS EM DESTAQUE", section_heading))
content.append(
    HRFlowable(width="100%", thickness=0.5, color=LIGHT, spaceBefore=0, spaceAfter=4)
)

projects = [
    {
        "name": "DataReplicator",
        "tech": "Python &bull; SQL Server &bull; Oracle &bull; PostgreSQL &bull; Telegram Bot",
        "url": "Projeto corporativo - Nazaria",
        "desc": "Ferramenta ETL para replica&ccedil;&atilde;o de mais de 130 entidades entre SQL Server, Oracle e PostgreSQL. Suporta processamento paralelo multi-thread, lotes de 50k linhas, sincroniza&ccedil;&atilde;o incremental e monitoramento via bot Telegram com notifica&ccedil;&otilde;es de erro.",
    },
    {
        "name": "Omniquery",
        "tech": "Python &bull; DuckDB &bull; SQL",
        "url": "github.com/SrMarinho/Omniquery",
        "desc": "Ferramenta ETL open-source que unifica consultas SQL em m&uacute;ltiplas fontes heterog&ecirc;neas (SQL Server, Oracle, PostgreSQL, CSV/XLSX) atrav&eacute;s de uma interface &uacute;nica, usando DuckDB como motor de processamento.",
    },
    {
        "name": "JobPilot",
        "tech": "Python &bull; Selenium &bull; Automa&ccedil;&atilde;o",
        "url": "github.com/SrMarinho/jobpilot",
        "desc": "Bot de automa&ccedil;&atilde;o para candidatura em vagas com avalia&ccedil;&atilde;o inteligente de fit, gerenciamento de estado das aplica&ccedil;&otilde;es e gera&ccedil;&atilde;o de relat&oacute;rios mensais.",
    },
    {
        "name": "Cantina Digital",
        "tech": "TypeScript &bull; Full-Stack",
        "url": "github.com/SrMarinho/cantina-digital",
        "desc": "Aplica&ccedil;&atilde;o web completa com cadastro de usu&aacute;rios, autentica&ccedil;&atilde;o, visualiza&ccedil;&atilde;o de card&aacute;pio e realiza&ccedil;&atilde;o de pedidos online.",
    },
]

for p in projects:
    content.append(
        Paragraph(
            "<b>"
            + p["name"]
            + "</b> &nbsp;<font color='#3182ce'>&bull;</font>&nbsp; "
            + p["tech"],
            project_name_style,
        )
    )
    content.append(Paragraph(p["url"], project_meta_style))
    content.append(Paragraph(p["desc"], bullet_style))
    content.append(Spacer(1, 0.04 * inch))

content.append(Paragraph("HABILIDADES T&Eacute;CNICAS", section_heading))
content.append(
    HRFlowable(width="100%", thickness=0.5, color=LIGHT, spaceBefore=0, spaceAfter=4)
)

skills = [
    ("Linguagens", "Python, TypeScript, JavaScript, SQL"),
    ("Back-end", "Node.js, Express, FastAPI, Flask, RESTful APIs"),
    ("Front-end", "React.js, Vue.js, Tailwind CSS, HTML5, CSS3"),
    ("Bancos de Dados", "PostgreSQL, SQL Server, Oracle, MongoDB, DuckDB"),
    ("SQL Avan&ccedil;ado", "CTEs, Window Functions, Indexing, Query Optimization"),
    ("DevOps &amp; Tooling", "Git, Docker, Linux, GitHub Actions, CI/CD"),
    ("Arquitetura", "SOLID, Design Patterns, Clean Code, Microsservi&ccedil;os"),
    (
        "ETL &amp; Automa&ccedil;&atilde;o",
        "ETL, RPA, Selenium, Web Scraping, Multi-threading",
    ),
    ("Metodologias", "Scrum, Agile, TDD"),
    (
        "Idiomas",
        "Portugu&ecirc;s (Nativo), Ingl&ecirc;s (Intermedi&aacute;rio - leitura t&eacute;cnica avan&ccedil;ada)",
    ),
]

skills_data = [
    [Paragraph(label, skill_label_style), Paragraph(value, skill_value_style)]
    for label, value in skills
]
skills_table = Table(skills_data, colWidths=[1.4 * inch, 5.9 * inch])
skills_table.setStyle(
    TableStyle(
        [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]
    )
)
content.append(skills_table)

content.append(Paragraph("FORMA&Ccedil;&Atilde;O ACAD&Ecirc;MICA", section_heading))
content.append(
    HRFlowable(width="100%", thickness=0.5, color=LIGHT, spaceBefore=0, spaceAfter=4)
)
content.append(
    Paragraph(
        "<b>P&oacute;s-gradua&ccedil;&atilde;o em Engenharia de Software</b> &nbsp;<font color='#3182ce'>(Cursando)</font>",
        edu_style,
    )
)
content.append(Paragraph("PUC Minas", company_period_style))
content.append(Spacer(1, 0.04 * inch))
content.append(
    Paragraph(
        "<b>Bacharelado em Ci&ecirc;ncia da Computa&ccedil;&atilde;o</b>", edu_style
    )
)
content.append(
    Paragraph("Universidade Est&aacute;cio de S&aacute;", company_period_style)
)

doc.build(content)
print("[OK] Curriculo profissional gerado!")
