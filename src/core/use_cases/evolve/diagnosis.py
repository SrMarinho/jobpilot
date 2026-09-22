"""Classifica incidente crônico em categoria acionável. Prompt e parsing puros.

Contar ocorrências diz *que* algo se repete; não diz *o que fazer*. As três
respostas possíveis para um mesmo WARNING repetido exigem ações opostas:

- o selector apodreceu → curar,
- a plataforma mudou o fluxo → consertar a expectativa (às vezes só o log),
- a feature morreu → aposentar e parar de tentar.

Tratar tudo como selector quebrado foi o erro que os 711 avisos de ``invite
modal`` revelaram: eram o caminho de sucesso sendo logado como falha. Uma cura
ali gastaria LLM pra sempre caçando um modal que não existe.

Uma chamada de LLM por lote, não por incidente: é mais barato e mantém a
classificação consistente entre itens que aparecem juntos. O formato de ida e
volta é texto delimitado por ``|``, o mesmo padrão que o ``job_evaluator`` e o
``form_extractor`` já usam — o contrato do provider é ``complete(str) -> str``,
sem JSON schema.

Uma categoria de propósito **não** gera patch: ``platform_changed``. Redesenhar
um fluxo não é validável por pytest, e autonomia onde não há verificação é
aposta, não automação.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CAT_SELECTOR = "selector"
CAT_PLATFORM_GONE = "platform_gone"
CAT_PLATFORM_CHANGED = "platform_changed"
CAT_BUG = "bug"
CAT_NOISE = "noise"

CATEGORIES = (
    CAT_SELECTOR,
    CAT_PLATFORM_GONE,
    CAT_PLATFORM_CHANGED,
    CAT_BUG,
    CAT_NOISE,
)

#: Categorias que podem virar trabalho automático. `platform_changed` fica
#: fora: vira mensagem no Telegram, com o diagnóstico, pro dono decidir.
ACTIONABLE = {CAT_SELECTOR, CAT_PLATFORM_GONE, CAT_BUG, CAT_NOISE}

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_LINE_RE = re.compile(
    r"^\s*(?P<sig>[a-f0-9]{6,12})\s*\|\s*(?P<cat>[a-z_]+)\s*\|\s*"
    r"(?P<conf>[0-9.]+)\s*\|\s*(?P<why>.+?)\s*$"
)


@dataclass(frozen=True, slots=True)
class Diagnosis:
    sig: str
    category: str
    confidence: float
    reason: str

    @property
    def actionable(self) -> bool:
        return self.category in ACTIONABLE

    @property
    def confident(self) -> bool:
        """Abaixo disto, só reporta — não age.

        Classificação incerta que dispara patch é pior que nenhuma
        classificação: gasta LLM e produz branch que ninguém quer.
        """
        return self.confidence >= 0.7


def build_diagnosis_prompt(incidents: list) -> str:
    """Pedido de classificação de um lote de incidentes."""
    blocos = []
    for incident in incidents:
        campos = ", ".join(sorted(incident.fields)) or "nenhum"
        amostra = (incident.samples[0] if incident.samples else "")[:220]
        blocos.append(
            f"ID: {incident.sig}\n"
            f"  tarefa: {incident.task}\n"
            f"  nível: {incident.level}\n"
            f"  ocorrências: {incident.count} em {incident.days_seen} dia(s)\n"
            f"  campo de selector citado: {campos}\n"
            f"  mensagem: {incident.template}\n"
            f"  amostra: {amostra}"
        )
    corpo = "\n\n".join(blocos)

    return f"""Você analisa logs de um robô de automação do LinkedIn (Playwright).
Cada item abaixo é uma falha que se repete há dias. Classifique cada um.

CATEGORIAS:
- selector: nosso seletor CSS/XPath parou de casar porque o HTML do site mudou.
  Sinal típico: mensagem cita um campo de selector e o elemento deveria existir.
- platform_gone: a funcionalidade deixou de existir na plataforma. Sinal
  típico: a própria página diz que o recurso foi descontinuado/removido.
- platform_changed: o fluxo da plataforma mudou, e a nossa expectativa é que
  está errada — não o seletor. Sinal típico: o aviso acontece mas a operação
  na verdade dá certo por outro caminho.
- bug: erro no nosso código (exceção, lógica, estado inconsistente).
- noise: comportamento esperado logado como aviso, ou condição transitória de
  ambiente (rede, concorrência, limite de recurso). Não precisa de correção.

FALHAS:

{corpo}

Responda UMA LINHA por item, exatamente neste formato:
ID|categoria|confianca|justificativa em uma frase

confianca é um número de 0 a 1. Use abaixo de 0.7 quando a evidência não
permitir decidir. Sem cabeçalho, sem markdown, sem numeração, sem comentário.

RESPOSTA:"""


def parse_diagnoses(raw: str) -> list[Diagnosis]:
    """Extrai as classificações. Linha malformada é ignorada, não adivinhada."""
    if not raw:
        return []
    saida: list[Diagnosis] = []
    vistos: set[str] = set()
    for linha in _THINK_RE.sub(" ", raw).splitlines():
        match = _LINE_RE.match(linha.strip().strip("`"))
        if not match:
            continue
        categoria = match["cat"].strip().lower()
        if categoria not in CATEGORIES:
            continue
        sig = match["sig"]
        if sig in vistos:
            continue
        try:
            confianca = float(match["conf"])
        except ValueError:
            continue
        vistos.add(sig)
        saida.append(
            Diagnosis(
                sig=sig,
                category=categoria,
                confidence=min(max(confianca, 0.0), 1.0),
                reason=match["why"][:300],
            )
        )
    return saida


def plan_action(incident, diagnosis: Diagnosis) -> tuple[str | None, str]:
    """``(tipo de job, explicação)``. ``None`` quando não deve virar trabalho.

    A explicação é sempre preenchida — inclusive quando não há ação — porque é
    ela que vai pro Telegram e pro histórico do incidente. "Não fiz nada e não
    digo por quê" é o comportamento que este sistema não pode ter.
    """
    from src.core.use_cases.evolve.queue import (
        KIND_DEMOTE_LOG,
        KIND_PATCH_BUG,
        KIND_RETIRE_FEATURE,
    )
    from src.core.use_cases.evolve.selector_registry import spec_for

    if not diagnosis.confident:
        return None, f"confiança baixa ({diagnosis.confidence:.2f}) — só reporta"

    if diagnosis.category == CAT_NOISE:
        # Não é job: é silenciar. Quem executa isso é o próprio scan.
        return None, "ruído — incidente silenciado por 30 dias"

    if diagnosis.category == CAT_PLATFORM_CHANGED:
        return None, (
            "fluxo da plataforma mudou — redesenho não é validável por pytest, "
            "então fica pra decisão humana"
        )

    if diagnosis.category == CAT_SELECTOR:
        campos = sorted(incident.fields)
        if not campos:
            return None, "sem campo de selector citado — não há o que promover"
        spec = spec_for(campos[0])
        if spec is None:
            return None, f"campo {campos[0]!r} não está no registry"
        if not spec.healable:
            return None, (
                f"campo {campos[0]!r} declarado incurável: "
                f"{spec.absent_note or 'clicável sem expect'}"
            )
        # A cura acontece no browser, não aqui: o drain não tem DOM. O que dá
        # pra fazer é deixar marcado para o próximo run que tocar o campo.
        return None, (
            f"campo {campos[0]!r} é curável — a cura acontece no próximo run "
            "que abrir essa página (precisa do DOM vivo)"
        )

    if diagnosis.category == CAT_PLATFORM_GONE:
        return (
            KIND_RETIRE_FEATURE,
            "feature descontinuada — aposentar e parar de tentar",
        )

    if diagnosis.category == CAT_BUG:
        if incident.level == "WARNING" and incident.fields:
            return KIND_DEMOTE_LOG, "aviso em caminho que pode não ser de erro"
        return KIND_PATCH_BUG, "bug no nosso código"

    return None, "categoria sem ação definida"
