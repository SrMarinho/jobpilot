from src.utils.telegram import _MAX_TEXT, _redact, _repair_400


def test_redact_tira_token_da_url():
    msg = "400 Client Error for url: https://api.telegram.org/bot123:ABC/sendMessage"
    assert "123:ABC" not in _redact(msg, "123:ABC")


def test_redact_sem_token_nao_mexe():
    assert _redact("erro", "") == "erro"


def test_html_invalido_cai_para_texto_puro():
    payload = {"text": "a < b", "parse_mode": "HTML"}
    assert _repair_400("Bad Request: can't parse entities", payload, None)
    assert "parse_mode" not in payload


def test_texto_longo_e_cortado():
    payload = {"text": "x" * 5000}
    assert _repair_400("Bad Request: message is too long", payload, None)
    assert len(payload["text"]) < _MAX_TEXT


def test_400_sem_conserto_nao_repete():
    payload = {"text": "oi", "chat_id": "1"}
    assert not _repair_400("Bad Request: chat not found", payload, None)
