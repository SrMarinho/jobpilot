"""Leitura dos logs e agrupamento de falha recorrente em incidente.

O modo de falha mais caro do projeto é silencioso: o selector não casa, o
``except`` genérico engole, e o run agendado "termina bem" sem fazer nada.
Ninguém percebe até olhar resultado ruim dias depois — ``campo='invite modal'``
falhou 711 vezes em 30 dias sem ninguém consertar.

Este módulo é a metade observadora: transforma ``logs/YYYY/MM/YYYYMMDD.log`` em
incidentes agrupados por assinatura, para que o resto do evolve decida o que
fazer. É puro de propósito (só stdlib, nenhum IO além de ler arquivo, nenhum
LLM) — é o módulo que precisa ser confiável antes de qualquer autonomia.

Duas realidades do log de verdade que o parser precisa aguentar:

1. **O file handler não é single-line.** Só o console usa
   ``SingleLineFormatter`` (``src/utils/logger.py``), então mensagem de
   exceção do Playwright ("Call log:" e seus passos) ocupa várias linhas.
2. **Escritas rasgadas.** Os runs agendados e o drain horário abrem o mesmo
   arquivo em processos diferentes; 0,67% das linhas aparecem cortadas no meio
   da palavra ("ool aberto" = "Postgres pool aberto" partido). Linha que não
   começa com cabeçalho é colada no registro anterior, o que reconstrói o
   rasgo, e o total é reportado em ``ScanStats`` — perda silenciosa de log num
   sistema que decide sozinho seria o pior default possível.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

# Cabeçalho escrito pelo file handler em src/utils/logger.py:
# "%(asctime)s - [%(run_id)s] - [%(run_type)s] - %(levelname)s - %(message)s"
_HEADER_RE = re.compile(
    r"^(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),(?P<ms>\d{3}) - "
    r"\[(?P<run_id>[^\]]*)\] - \[(?P<task>[^\]]*)\] - "
    r"(?P<level>[A-Z]+) - (?P<msg>.*)$"
)

# Uma mensagem de Playwright com "Call log:" inteiro passa de 2 KB e não
# acrescenta nada à assinatura (o template corta em 120 chars). O teto evita
# carregar tudo isso em memória para milhares de registros.
_MSG_CAP = 600

_LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}

# Campo que o resolver de selectors nomeia na falha (`campo='invite modal'`).
# É o que liga um incidente a uma constante de page — sobrevive à normalização.
_FIELD_RE = re.compile(r"campo=['\"]?(?P<field>[^'\",;:]+)")


@dataclass(frozen=True, slots=True)
class LogRecord:
    ts: datetime
    run_id: str
    task: str
    level: str
    msg: str

    @property
    def day(self) -> date:
        return self.ts.date()


def parse_lines(lines: Iterable[str]) -> tuple[list[LogRecord], int]:
    """Registros + quantas linhas eram continuação/rasgo.

    Linha com cabeçalho abre um registro; qualquer outra é apensada à mensagem
    do registro aberto. Continuação antes do primeiro cabeçalho é descartada
    (arquivo começando no meio de um registro rasgado).
    """
    records: list[LogRecord] = []
    orphans = 0
    head: dict | None = None
    parts: list[str] = []

    def flush() -> None:
        if head is None:
            return
        msg = " ".join(p for p in parts if p).strip()[:_MSG_CAP]
        records.append(
            LogRecord(
                ts=head["ts"],
                run_id=head["run_id"],
                task=head["task"],
                level=head["level"],
                msg=msg,
            )
        )

    for raw in lines:
        line = raw.rstrip("\n").rstrip("\r")
        match = _HEADER_RE.match(line)
        if match:
            flush()
            head = {
                "ts": datetime.strptime(match["ts"], "%Y-%m-%d %H:%M:%S"),
                "run_id": match["run_id"],
                "task": match["task"],
                "level": match["level"],
            }
            parts = [match["msg"]]
            continue
        orphans += 1
        if head is not None:
            parts.append(line.strip())
    flush()
    return records, orphans


def log_files(log_dir: Path, since: date, until: date) -> list[Path]:
    """Arquivos ``YYYY/MM/YYYYMMDD.log`` no intervalo, em ordem de data.

    Itera por data em vez de varrer a árvore: o diretório acumula anos de log e
    uma varredura completa cresce sem limite, enquanto a janela é sempre curta.
    """
    out: list[Path] = []
    day = since
    while day <= until:
        candidate = log_dir / f"{day:%Y}" / f"{day:%m}" / f"{day:%Y%m%d}.log"
        if candidate.exists():
            out.append(candidate)
        day += timedelta(days=1)
    return out


def read_records(
    log_dir: Path, *, since: date, until: date, min_level: str = "WARNING"
) -> tuple[list[LogRecord], int]:
    """Registros do intervalo com nível >= ``min_level``, e total de órfãs."""
    floor = _LEVEL_ORDER.get(min_level, 30)
    records: list[LogRecord] = []
    orphans = 0
    for path in log_files(log_dir, since, until):
        # errors="replace": escrita rasgada pode partir um caractere UTF-8 em
        # dois flushes, e um UnicodeDecodeError aqui cegaria o scan inteiro.
        with path.open(encoding="utf-8", errors="replace") as fh:
            parsed, orphan_count = parse_lines(fh)
        orphans += orphan_count
        records.extend(r for r in parsed if _LEVEL_ORDER.get(r.level, 0) >= floor)
    return records, orphans


# ── normalização ────────────────────────────────────────────────────────────
# Ordem importa: o específico vem antes do genérico, senão o genérico come o
# específico (um id de 19 dígitos viraria <n> antes de virar <id>).
_SUBS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"https?://\S+"), "<url>"),
    (re.compile(r"\burn:li:[\w:%.-]+"), "<id>"),
    (re.compile(r"[A-Za-z]:\\[^\s'\"]+"), "<path>"),
    (re.compile(r"(?:/[\w.-]+){2,}/?"), "<path>"),
    (re.compile(r"\d{4}-\d\d-\d\d(?:[ T]\d\d:\d\d:\d\d(?:[.,]\d+)?)?"), "<ts>"),
    (re.compile(r"\b\d\d:\d\d:\d\d\b"), "<ts>"),
    # Blob citado longo (head de innerText da página) varia a cada run e
    # explodiria a mesma falha em centenas de assinaturas. É o que faz os 711
    # 'invite modal' virarem UM incidente em vez de 711.
    (re.compile(r"'[^']{40,}'"), "'<text>'"),
    (re.compile(r'"[^"]{40,}"'), '"<text>"'),
    (re.compile(r"\b\d{6,}\b"), "<id>"),
    (re.compile(r"\b\d{2,}\b"), "<n>"),
)

_WS_RE = re.compile(r"\s+")
_TEMPLATE_CAP = 120


def normalize(msg: str) -> str:
    """Mensagem sem as partes que variam por run (ids, urls, datas, blobs)."""
    out = msg
    for pattern, repl in _SUBS:
        out = pattern.sub(repl, out)
    return _WS_RE.sub(" ", out).strip()


def template_of(msg: str) -> str:
    return normalize(msg)[:_TEMPLATE_CAP]


def signature(level: str, task: str, msg: str) -> str:
    """Assinatura estável de uma falha.

    Hash em vez de clustering fuzzy: determinístico, testável e sem
    dependência. O custo é que duas parafrases da mesma falha viram dois
    incidentes — por isso o ``template`` legível anda junto do hash.
    """
    key = f"{level}|{task}|{template_of(msg)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def extract_field(msg: str) -> str | None:
    """Nome do campo de selector citado na mensagem, se houver."""
    match = _FIELD_RE.search(msg)
    if not match:
        return None
    return match["field"].strip() or None


# ── agrupamento ─────────────────────────────────────────────────────────────
@dataclass(slots=True)
class Incident:
    sig: str
    level: str
    task: str
    template: str
    count: int = 0
    days: set[date] = field(default_factory=set)
    tasks: set[str] = field(default_factory=set)
    fields: set[str] = field(default_factory=set)
    samples: list[str] = field(default_factory=list)
    first_seen: datetime | None = None
    last_seen: datetime | None = None

    @property
    def days_seen(self) -> int:
        return len(self.days)

    def add(self, record: LogRecord) -> None:
        self.count += 1
        self.days.add(record.day)
        self.tasks.add(record.task)
        found = extract_field(record.msg)
        if found:
            self.fields.add(found)
        if len(self.samples) < 2:
            self.samples.append(record.msg)
        if self.first_seen is None or record.ts < self.first_seen:
            self.first_seen = record.ts
        if self.last_seen is None or record.ts > self.last_seen:
            self.last_seen = record.ts


@dataclass(slots=True)
class ScanStats:
    """O que o scan viu — inclusive o que não conseguiu ler."""

    files: int = 0
    records: int = 0
    orphan_lines: int = 0
    incidents: int = 0
    chronic: int = 0


def group_incidents(records: Iterable[LogRecord]) -> list[Incident]:
    """Incidentes por assinatura, do mais frequente ao menos."""
    by_sig: dict[str, Incident] = {}
    for record in records:
        sig = signature(record.level, record.task, record.msg)
        incident = by_sig.get(sig)
        if incident is None:
            incident = Incident(
                sig=sig,
                level=record.level,
                task=record.task,
                template=template_of(record.msg),
            )
            by_sig[sig] = incident
        incident.add(record)
    return _sorted(by_sig.values())


def _sorted(incidents: Iterable[Incident]) -> list[Incident]:
    return sorted(incidents, key=lambda i: (-i.count, i.template))


def merge_by_field(incidents: Iterable[Incident]) -> list[Incident]:
    """Funde incidentes que já sabemos ser o mesmo problema.

    O preço da assinatura por hash é a parafrase: a mesma falha de ``invite
    modal`` aparece como duas assinaturas (707 + 4) só porque uma variante da
    mensagem ganhou o sufixo ``; página: '<text>'``. Quando os incidentes
    concordam em nível, task **e** no campo de selector citado, isso não é
    ambiguidade — é a mesma quebra escrita de dois jeitos, e mandar as duas pro
    diagnóstico gastaria dois slots de LLM pra decidir a mesma coisa.

    Funde só com ``fields`` não-vazio: sem o nome do campo não há evidência
    suficiente pra afirmar que são o mesmo problema, e fundir por palpite
    esconderia falhas distintas atrás de um template só.
    """
    merged: dict[tuple, Incident] = {}
    passthrough: list[Incident] = []
    for incident in _sorted(incidents):
        if not incident.fields:
            passthrough.append(incident)
            continue
        key = (incident.level, incident.task, tuple(sorted(incident.fields)))
        first = merged.get(key)
        if first is None:
            # O primeiro é o de maior contagem (lista já ordenada), então o
            # template que sobrevive é o da variante dominante.
            merged[key] = incident
            continue
        first.count += incident.count
        first.days |= incident.days
        first.tasks |= incident.tasks
        first.samples.extend(incident.samples[: 2 - len(first.samples)])
        if incident.first_seen and (
            first.first_seen is None or incident.first_seen < first.first_seen
        ):
            first.first_seen = incident.first_seen
        if incident.last_seen and (
            first.last_seen is None or incident.last_seen > first.last_seen
        ):
            first.last_seen = incident.last_seen
    return _sorted([*merged.values(), *passthrough])


# Crônico = volume E persistência. Só volume pegaria uma tempestade de uma
# noite (rede caída); só persistência pegaria ruído diário de um evento.
CHRONIC_MIN_COUNT = 10
CHRONIC_MIN_DAYS = 3
DEFAULT_WINDOW_DAYS = 14


def is_chronic(
    incident: Incident,
    *,
    min_count: int = CHRONIC_MIN_COUNT,
    min_days: int = CHRONIC_MIN_DAYS,
) -> bool:
    return incident.count >= min_count and incident.days_seen >= min_days


def chronic_only(
    incidents: Iterable[Incident],
    *,
    min_count: int = CHRONIC_MIN_COUNT,
    min_days: int = CHRONIC_MIN_DAYS,
) -> Iterator[Incident]:
    for incident in incidents:
        if is_chronic(incident, min_count=min_count, min_days=min_days):
            yield incident


def scan(
    log_dir: Path,
    *,
    days: int = DEFAULT_WINDOW_DAYS,
    today: date | None = None,
    min_level: str = "WARNING",
    min_count: int = CHRONIC_MIN_COUNT,
    min_days: int = CHRONIC_MIN_DAYS,
) -> tuple[list[Incident], ScanStats]:
    """Varredura completa: (incidentes ordenados, estatísticas)."""
    until = today or date.today()
    since = until - timedelta(days=days - 1)
    records, orphans = read_records(
        log_dir, since=since, until=until, min_level=min_level
    )
    incidents = merge_by_field(group_incidents(records))
    stats = ScanStats(
        files=len(log_files(log_dir, since, until)),
        records=len(records),
        orphan_lines=orphans,
        incidents=len(incidents),
        chronic=sum(
            1
            for i in incidents
            if is_chronic(i, min_count=min_count, min_days=min_days)
        ),
    )
    return incidents, stats
