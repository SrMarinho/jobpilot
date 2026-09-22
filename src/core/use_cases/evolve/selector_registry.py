"""O que cada campo de selector significa, e onde ele mora no código.

O log só diz ``campo='invite modal'``. Pra curar isso é preciso saber três
coisas que a string não carrega:

1. **O que o campo quer dizer** — sem intenção semântica, o LLM recebe uma
   lista de elementos e um nome em inglês e chuta.
2. **Onde a constante vive** — pra promover um candidato validado de volta pro
   código-fonte (``_INVITE_MODAL`` em ``people_search_page.py``).
3. **O que NÃO pode acontecer** — o item mais importante. Um candidato proposto
   por LLM para um campo clicável vai ser clicado de verdade, e clicar no botão
   errado manda convite, DM ou denúncia em nome do usuário. Daí ``expect``:
   regex que o nome acessível do elemento tem que casar. **Campo clicável sem
   ``expect`` é declarado incurável** — melhor não curar do que clicar no
   escuro.

Chave = o próprio nome do campo, e não ``<page>.<campo>``: é tudo que a linha
de log oferece (``extract_field`` devolve só o nome), então uma chave composta
não teria de onde ser reconstruída. Os nomes já são globalmente únicos —
"linkedin job title" vs "indeed job title" — e ``tests/test_selector_registry``
trava isso, transformando a convenção numa garantia.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

PAGES = "src.automation.pages"


@dataclass(frozen=True, slots=True)
class FieldSpec:
    field: str
    module: str
    constant: str
    intent: str
    # "page" = documento inteiro; "dialog" = dentro do modal aberto; "card" =
    # dentro de um card da lista (o resolver recebe o card como root).
    scope: str = "page"
    # Quantos elementos um candidato pode casar sem ser genérico demais.
    # Container e botão: 1. Texto que aparece repetido no layout: mais.
    max_matches: int = 1
    # Regex (case-insensitive) que o nome acessível precisa casar. Obrigatório
    # para campo clicável — ver docstring do módulo.
    expect: str | None = None
    # O elemento é clicado depois de resolvido?
    clicked: bool = False
    # Ausência é comportamento normal, não quebra. Nunca tentar curar.
    expected_absent: bool = False
    absent_note: str = ""

    @property
    def healable(self) -> bool:
        """Só cura o que dá pra validar sem risco de clique errado."""
        if self.expected_absent:
            return False
        if self.clicked and not self.expect:
            return False
        return True

    def resolve_constant(self) -> list[str]:
        """Valor atual da constante no código (fonte da verdade declarada)."""
        module = importlib.import_module(self.module)
        return getattr(module, self.constant)


def _spec(field: str, module: str, constant: str, intent: str, **kwargs) -> FieldSpec:
    return FieldSpec(
        field=field,
        module=f"{PAGES}.{module}",
        constant=constant,
        intent=intent,
        **kwargs,
    )


_SPECS: tuple[FieldSpec, ...] = (
    # ── LinkedIn: busca de pessoas / convites ──────────────────────────────
    _spec(
        "invite modal",
        "people_search_page",
        "_INVITE_MODAL",
        "container do modal de confirmação que o LinkedIn abre depois do clique "
        "em Conectar, e que contém o botão de enviar o convite",
        scope="page",
        expected_absent=True,
        absent_note=(
            "O LinkedIn 2026 manda boa parte dos convites SEM abrir modal — o "
            "botão só vira 'Pendente'. A ausência é o caminho de sucesso, "
            "confirmado por pending_count() em invitation_handler. Os 711 "
            "WARNINGs de setembro são falso alarme: curar aqui seria caçar um "
            "modal que não existe mais. O conserto é no nível do log."
        ),
    ),
    _spec(
        "invite modal close",
        "people_search_page",
        "_MODAL_CLOSE",
        "botão de fechar/descartar o modal de convite aberto",
        scope="dialog",
        clicked=True,
        expect=r"(fechar|dismiss|close|descartar)",
    ),
    _spec(
        "withdraw invite modal",
        "people_search_page",
        "_WITHDRAW_MODAL",
        "aviso de que o convite para essa pessoa já foi enviado e pode ser "
        "retirado — serve para detectar e pular, não para clicar",
        scope="dialog",
        expect=r"(retirar|withdraw)",
    ),
    _spec(
        "send invite button",
        "people_search_page",
        "_SEND_INVITE",
        "botão que envia o convite de conexão sem adicionar nota, dentro do "
        "modal de confirmação",
        scope="dialog",
        clicked=True,
        expect=r"(enviar|send)",
    ),
    # ── LinkedIn: busca de vagas ───────────────────────────────────────────
    _spec(
        "linkedin job title",
        "jobs_search_page",
        "_TITLE",
        "título da vaga no painel de detalhe da vaga selecionada",
        max_matches=2,
    ),
    _spec(
        "linkedin company name",
        "jobs_search_page",
        "_COMPANY",
        "nome da empresa que publicou a vaga selecionada",
        max_matches=2,
    ),
    _spec(
        "linkedin job description",
        "jobs_search_page",
        "_DESCRIPTION",
        "texto completo da descrição da vaga selecionada",
    ),
    _spec(
        "easy apply button",
        "jobs_search_page",
        "_EASY_APPLY",
        "botão de Candidatura Simplificada (Easy Apply) da vaga selecionada — "
        "abre o modal de candidatura, não envia nada por si só",
        clicked=True,
        expect=r"(candidatura simplificada|easy apply|candidat)",
    ),
    # ── Indeed ─────────────────────────────────────────────────────────────
    _spec(
        "indeed job title",
        "indeed_jobs_page",
        "_TITLE",
        "título da vaga no painel de detalhe do Indeed",
        max_matches=2,
    ),
    _spec(
        "indeed company name",
        "indeed_jobs_page",
        "_COMPANY",
        "nome da empresa da vaga aberta no Indeed",
        max_matches=2,
    ),
    _spec(
        "indeed job description",
        "indeed_jobs_page",
        "_DESCRIPTION",
        "texto completo da descrição da vaga no Indeed",
    ),
    _spec(
        "indeed apply button",
        "indeed_jobs_page",
        "_APPLY_BTN",
        "botão de candidatura da vaga no Indeed",
        clicked=True,
        expect=r"(apply|candidat|aplicar)",
    ),
    # ── Glassdoor ──────────────────────────────────────────────────────────
    _spec(
        "glassdoor job title",
        "glassdoor_jobs_page",
        "_TITLE",
        "título da vaga no painel de detalhe do Glassdoor",
        max_matches=2,
    ),
    _spec(
        "glassdoor job description",
        "glassdoor_jobs_page",
        "_DESCRIPTION",
        "texto completo da descrição da vaga no Glassdoor",
    ),
    _spec(
        "glassdoor card title",
        "glassdoor_jobs_page",
        "_CARD_TITLE",
        "título da vaga dentro de um card da lista de resultados do Glassdoor",
        scope="card",
    ),
    _spec(
        "glassdoor card company",
        "glassdoor_jobs_page",
        "_CARD_COMPANY",
        "nome da empresa dentro de um card da lista do Glassdoor",
        scope="card",
    ),
    _spec(
        "glassdoor modal close",
        "glassdoor_jobs_page",
        "_MODAL_CLOSE",
        "botão de fechar o modal de cadastro/login que o Glassdoor abre sobre "
        "a listagem",
        scope="dialog",
        clicked=True,
        expect=r"(fechar|close|dismiss)",
    ),
    _spec(
        "glassdoor apply button",
        "glassdoor_jobs_page",
        "_APPLY_BTN_BY_TEXT",
        "botão de candidatura da vaga no Glassdoor, localizado pelo texto",
        clicked=True,
        expect=r"(apply|candidat|aplicar)",
    ),
)

FIELD_SPECS: dict[str, FieldSpec] = {spec.field: spec for spec in _SPECS}

# Campos que os resolvers de selectors NÃO servem hoje, e que por isso ficam
# fora do alcance da cura. Documentado em vez de esquecido: enquanto a lista de
# candidatos vive numa variável local (e não numa constante de módulo), não há
# o que sobrescrever nem o que promover.
UNREACHABLE = {
    "connect button": (
        "people_search_page.get_connect_btn monta os xpaths numa lista local e "
        "itera à mão, sem passar por first_enabled. Migrar para o resolver é "
        "pré-requisito pra curar esse campo."
    ),
    "feed posts": ("feed_page usa locator cru e walk-up de botões; mesma situação."),
    "autopost editor": (
        "feed_composer_page resolve em camadas próprias (estrutural→aria→texto) "
        "com alerta próprio no Telegram."
    ),
}


def spec_for(field: str) -> FieldSpec | None:
    return FIELD_SPECS.get(field)


def healable_fields() -> list[str]:
    return sorted(f for f, spec in FIELD_SPECS.items() if spec.healable)
