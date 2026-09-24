from src.utils.logger import redact_secrets

_TOKEN = "8123456789:AAGkNnKMBNktLmWaNEdeDHBlQU-RNvBVsXy"


def test_mascara_token_colado_em_bot_na_url():
    msg = f"400 Client Error for url: https://api.telegram.org/bot{_TOKEN}/sendMessage"
    out = redact_secrets(msg)
    assert _TOKEN not in out
    assert "bot<telegram-token>/sendMessage" in out


def test_nao_mexe_em_horario_nem_texto_comum():
    msg = "2026-09-19 14:10:48,544 - [hired] - Relatório enviado"
    assert redact_secrets(msg) == msg
