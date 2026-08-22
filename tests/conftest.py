"""Isolamento dos testes contra o ambiente real.

O `.env` do desenvolvedor aponta pra um Postgres de produção — instanciar um
tracker com ele setado grava no histórico de verdade. Aqui `DATABASE_URL` é
zerado antes de qualquer import do projeto, forçando o backend JSON local, e
`LOG_DIR` é apontado pra um tmpdir para a suíte não sujar `logs/`.
"""

import os
import tempfile

os.environ["DATABASE_URL"] = ""
# Log fora de logs/: a suite exercita caminhos de erro de proposito, e esses
# ERRORs no log de producao mascaram os incidentes reais.
os.environ["LOG_DIR"] = tempfile.mkdtemp(prefix="jobpilot-test-logs-")
os.environ.setdefault("USER_NAME", "Test User")
os.environ.setdefault("USER_HEADLINE", "Test Headline")
