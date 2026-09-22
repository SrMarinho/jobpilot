"""Autoevolução: o projeto observa suas próprias falhas e se conserta.

Camadas, em ordem de autonomia:

- ``log_scan`` + ``incident_store`` — observa: agrupa falha recorrente em
  incidente e lembra o que já foi decidido sobre cada assinatura.
- ``selector_registry`` — declara o que cada campo de selector significa, onde
  a constante vive e, sobretudo, o que um candidato jamais pode ser.
- ``selector_store`` — guarda o que foi aprendido em runtime e cobra as regras
  de segurança antes de aceitar qualquer candidato.
"""

from .incident_store import IncidentState, IncidentStore
from .log_scan import Incident, ScanStats, is_chronic, scan, signature
from .selector_registry import FIELD_SPECS, FieldSpec, healable_fields, spec_for
from .selector_store import (
    SelectorStore,
    is_safe_candidate,
    learned_for,
    refresh_overrides,
)

__all__ = [
    "FIELD_SPECS",
    "FieldSpec",
    "Incident",
    "IncidentState",
    "IncidentStore",
    "ScanStats",
    "SelectorStore",
    "healable_fields",
    "is_chronic",
    "is_safe_candidate",
    "learned_for",
    "refresh_overrides",
    "scan",
    "signature",
    "spec_for",
]
