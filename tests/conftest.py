"""Isolamento dos testes contra o ambiente real.

O `.env` do desenvolvedor aponta pra um Postgres de produção — instanciar um
tracker com ele setado grava no histórico de verdade. Aqui `DATABASE_URL` é
zerado antes de qualquer import do projeto, forçando o backend JSON local.
"""

import os

os.environ["DATABASE_URL"] = ""
os.environ.setdefault("USER_NAME", "Test User")
os.environ.setdefault("USER_HEADLINE", "Test Headline")
