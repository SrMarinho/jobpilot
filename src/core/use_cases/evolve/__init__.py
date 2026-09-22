"""Autoevolução: o projeto observa suas próprias falhas e se conserta.

Nesta fase o pacote só **observa**: ``log_scan`` agrupa falha recorrente em
incidente e ``incident_store`` lembra o que já foi decidido sobre cada uma.
"""

from .incident_store import IncidentStore, IncidentState
from .log_scan import Incident, ScanStats, is_chronic, scan, signature

__all__ = [
    "Incident",
    "IncidentState",
    "IncidentStore",
    "ScanStats",
    "is_chronic",
    "scan",
    "signature",
]
