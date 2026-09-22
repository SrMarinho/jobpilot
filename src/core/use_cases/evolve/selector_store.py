"""Selectors aprendidos em runtime, e as regras que um candidato tem que passar.

Quando o layout muda, a lista de candidatos declarada na page fica obsoleta e o
run morre em silêncio. O store guarda o que foi aprendido depois, para que o
próximo run já comece com o selector certo — sem esperar deploy.

Duas responsabilidades, ambas com motivo:

**Regras de segurança** (``is_safe_candidate``) — puras, testáveis, e a
primeira barreira contra um LLM criativo. A mais importante é a vírgula de
topo: ``locator("a, b")`` casa os dois seletores ao mesmo tempo e estoura o
strict mode do Playwright — bug que o projeto já pagou uma vez e documentou em
``selectors.py``. Deixar o LLM reintroduzir isso seria repetir de graça.

**Contabilidade de acerto/erro** — um aprendido não é verdade eterna: o layout
muda de novo. Cada candidato acumula ``hits``/``misses`` e é descartado depois
de 3 erros seguidos, senão o store viraria um cemitério de seletores mortos que
custa 1s cada na frente da fila.

Escrita é explícita (``flush``) porque isto roda no hot path: gravar a cada
resolve faria IO dentro do loop de scraping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timedelta
from pathlib import Path

from src.config.settings import files_dir, logger
from src.core.persistence.doc_repo import DocRepo

OVERRIDES_FILE = files_dir / "selector_overrides.json"

# Depois de 3 runs sem casar, o aprendido é lixo: o layout mudou outra vez.
MAX_MISSES = 3
# Depois de 3 curas falhas, para de gastar LLM nesse campo.
MAX_HEAL_FAILURES = 3
HEAL_COOLDOWN_HOURS = 24

# O teto existe pra barrar seletor desgovernado de LLM, não pra proibir xpath
# longo legítimo: o `_EASY_APPLY` do jobs_search_page tem 573 chars por causa
# do translate() que faz case-fold com acento. Um limite de 300 reprovaria
# código que já funciona — foi o teste de contrato que apontou isso.
_MAX_LEN = 800
# Seletor que casa "qualquer coisa" passaria a validação de contagem por acaso
# e depois clicaria no elemento errado.
_TOO_BROAD = frozenset(
    {"*", "html", "body", "div", "span", "a", "button", "p", "li", "ul", "main"}
)


def _strip_xpath(selector: str) -> tuple[str, bool]:
    if selector.startswith("xpath="):
        return selector[len("xpath=") :], True
    return selector, False


def _has_top_level_comma(selector: str) -> bool:
    """Vírgula fora de parênteses/colchetes/aspas = lista de seletores.

    ``[aria-label='a,b']`` e ``:is(a,b)`` são legítimos; ``a, b`` no topo não.
    """
    depth = 0
    quote: str | None = None
    for char in selector:
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "'\"":
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            return True
    return False


def is_safe_candidate(selector: str) -> tuple[bool, str]:
    """``(ok, motivo)``. Motivo preenchido só quando rejeita."""
    if not selector or not selector.strip():
        return False, "vazio"
    selector = selector.strip()
    if len(selector) > _MAX_LEN:
        return False, f"longo demais ({len(selector)} chars)"
    if "\n" in selector:
        return False, "quebra de linha"
    if _has_top_level_comma(selector):
        # Ver docstring do módulo: estoura strict mode quando as duas variantes
        # coexistem, e o except genérico esconde isso como "campo vazio".
        return False, "vírgula de topo (casaria dois seletores e estoura strict mode)"

    body, is_xpath = _strip_xpath(selector)
    if not body.strip():
        return False, "xpath vazio"
    if is_xpath:
        if not body.startswith(("/", "(", ".")):
            return False, "xpath não começa com / ( ou ."
        return True, ""
    if body.lower() in _TOO_BROAD:
        return False, f"genérico demais ({body})"
    if re.fullmatch(r"[a-z]+\s*>\s*[a-z]+", body.lower()):
        return False, f"genérico demais ({body})"
    return True, ""


@dataclass(slots=True)
class LearnedCandidate:
    sel: str
    learned_at: str
    hits: int = 0
    misses: int = 0
    source: str = "heal"

    def as_doc(self) -> dict:
        return {
            "sel": self.sel,
            "learned_at": self.learned_at,
            "hits": self.hits,
            "misses": self.misses,
            "source": self.source,
        }

    @classmethod
    def from_doc(cls, doc: dict) -> LearnedCandidate:
        return cls(
            sel=doc["sel"],
            learned_at=doc.get("learned_at", ""),
            hits=int(doc.get("hits", 0) or 0),
            misses=int(doc.get("misses", 0) or 0),
            source=doc.get("source", "heal"),
        )


@dataclass(slots=True)
class FieldOverride:
    candidates: list[LearnedCandidate] = dc_field(default_factory=list)
    last_heal_attempt: str | None = None
    heal_failures: int = 0
    promoted_commit: str | None = None
    unhealable: bool = False
    note: str = ""

    def as_doc(self) -> dict:
        return {
            "candidates": [c.as_doc() for c in self.candidates],
            "last_heal_attempt": self.last_heal_attempt,
            "heal_failures": self.heal_failures,
            "promoted_commit": self.promoted_commit,
            "unhealable": self.unhealable,
            "note": self.note,
        }

    @classmethod
    def from_doc(cls, doc: dict) -> FieldOverride:
        return cls(
            candidates=[
                LearnedCandidate.from_doc(c) for c in doc.get("candidates", [])
            ],
            last_heal_attempt=doc.get("last_heal_attempt"),
            heal_failures=int(doc.get("heal_failures", 0) or 0),
            promoted_commit=doc.get("promoted_commit"),
            unhealable=bool(doc.get("unhealable", False)),
            note=doc.get("note", ""),
        )

    def in_cooldown(self, *, now: datetime | None = None) -> bool:
        """Falhou há pouco? Não insiste — cura custa LLM e tempo de browser."""
        if not self.last_heal_attempt:
            return False
        try:
            last = datetime.fromisoformat(self.last_heal_attempt)
        except ValueError:
            return False
        return (now or datetime.now()) - last < timedelta(hours=HEAL_COOLDOWN_HOURS)


class SelectorStore:
    def __init__(self, repo: DocRepo | None = None):
        self._repo = repo or DocRepo("selector_overrides", json_file=OVERRIDES_FILE)
        self._data = self._repo.load()
        self._data.setdefault("version", 1)
        self._data.setdefault("fields", {})
        self._dirty = False

    # ── leitura ─────────────────────────────────────────────────────────────
    def override(self, field: str) -> FieldOverride:
        return FieldOverride.from_doc(self._data["fields"].get(field, {}))

    def candidates(self, field: str) -> list[str]:
        """Aprendidos do campo, do mais confiável ao menos."""
        override = self.override(field)
        ranked = sorted(
            override.candidates, key=lambda c: (-(c.hits - c.misses), c.learned_at)
        )
        return [c.sel for c in ranked]

    def as_dict(self) -> dict[str, list[str]]:
        """Mapa campo → aprendidos, para o cache do resolver."""
        return {
            field: self.candidates(field)
            for field in self._data["fields"]
            if self.candidates(field)
        }

    def fields(self) -> list[str]:
        return sorted(self._data["fields"])

    # ── escrita ─────────────────────────────────────────────────────────────
    def learn(self, field: str, selector: str, *, source: str = "heal") -> bool:
        """Registra um candidato validado. ``False`` se recusado ou já existe."""
        ok, reason = is_safe_candidate(selector)
        if not ok:
            logger.warning(
                f"[evolve] candidato recusado campo={field!r}: {reason} ({selector!r})"
            )
            return False
        override = self.override(field)
        if any(c.sel == selector for c in override.candidates):
            return False
        override.candidates.insert(
            0,
            LearnedCandidate(
                sel=selector,
                learned_at=datetime.now().isoformat(timespec="seconds"),
                source=source,
            ),
        )
        override.heal_failures = 0
        self._put(field, override)
        return True

    def record_hit(self, field: str, selector: str) -> None:
        override = self.override(field)
        for candidate in override.candidates:
            if candidate.sel == selector:
                candidate.hits += 1
                candidate.misses = 0
                self._put(field, override)
                return

    def record_miss(self, field: str) -> None:
        """Nenhum aprendido casou — todos erraram uma vez."""
        override = self.override(field)
        if not override.candidates:
            return
        for candidate in override.candidates:
            candidate.misses += 1
        self._put(field, override)

    def prune(self, field: str | None = None) -> list[str]:
        """Descarta aprendidos que erraram demais. Devolve o que saiu."""
        alvos = [field] if field else list(self._data["fields"])
        removidos: list[str] = []
        for nome in alvos:
            override = self.override(nome)
            manter = [c for c in override.candidates if c.misses < MAX_MISSES]
            if len(manter) != len(override.candidates):
                removidos.extend(
                    c.sel for c in override.candidates if c.misses >= MAX_MISSES
                )
                override.candidates = manter
                self._put(nome, override)
        if removidos:
            logger.info(
                f"[evolve] {len(removidos)} selector(es) aprendido(s) descartado(s) "
                f"após {MAX_MISSES} erros"
            )
        return removidos

    def note_heal_attempt(self, field: str, *, ok: bool) -> FieldOverride:
        override = self.override(field)
        override.last_heal_attempt = datetime.now().isoformat(timespec="seconds")
        if ok:
            override.heal_failures = 0
        else:
            override.heal_failures += 1
            if override.heal_failures >= MAX_HEAL_FAILURES:
                # Não é desistência silenciosa: o campo continua reportado como
                # incidente, só para de consumir LLM a cada run.
                override.unhealable = True
                override.note = (
                    f"{MAX_HEAL_FAILURES} curas falharam; só reporta a partir daqui"
                )
                logger.warning(
                    f"[evolve] campo={field!r} marcado incurável após "
                    f"{MAX_HEAL_FAILURES} tentativas"
                )
        self._put(field, override)
        return override

    def mark_promoted(self, field: str, commit: str) -> None:
        override = self.override(field)
        override.promoted_commit = commit
        self._put(field, override)

    def forget(self, field: str) -> bool:
        if field in self._data["fields"]:
            del self._data["fields"][field]
            self._dirty = True
            self.flush()
            return True
        return False

    # ── persistência ────────────────────────────────────────────────────────
    def _put(self, field: str, override: FieldOverride) -> None:
        self._data["fields"][field] = override.as_doc()
        self._dirty = True

    def flush(self) -> bool:
        """Grava se houver mudança. Chamado no fim do run, não no hot path."""
        if not self._dirty:
            return False
        self._repo.save(self._data)
        self._dirty = False
        return True


# ── cache de processo, para o resolver ──────────────────────────────────────
# `first_visible` roda dentro do loop de scraping: ler o doc a cada chamada
# seria IO no hot path. Carrega uma vez por processo e recarrega só quando algo
# aprendeu (refresh explícito).
_CACHE: dict[str, list[str]] | None = None
_STORE: SelectorStore | None = None


def store() -> SelectorStore:
    global _STORE
    if _STORE is None:
        _STORE = SelectorStore()
    return _STORE


def learned_for(field: str) -> list[str]:
    """Candidatos aprendidos do campo. Nunca levanta — o resolver depende disso."""
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = store().as_dict()
        except Exception as e:
            # Store quebrado não pode derrubar scraping: sem override, o
            # comportamento é exatamente o de antes desta feature existir.
            logger.warning(f"[evolve] overrides indisponíveis: {e}")
            _CACHE = {}
    return _CACHE.get(field, [])


def refresh_overrides() -> None:
    """Descarta o cache (após aprender algo, ou em teste)."""
    global _CACHE, _STORE
    _CACHE = None
    _STORE = None


def overrides_path() -> Path:
    return OVERRIDES_FILE
