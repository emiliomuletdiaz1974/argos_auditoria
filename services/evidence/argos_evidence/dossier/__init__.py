"""Campaign dossier: canonical JSON and its PDF (ARG-067)."""

from argos_evidence.dossier.build import (
    DossierError,
    DossierRecord,
    assemble,
    write_dossier,
)
from argos_evidence.dossier.render import ASSISTED_MARK, qr_payload, render_pdf

__all__ = [
    "ASSISTED_MARK",
    "DossierError",
    "DossierRecord",
    "assemble",
    "qr_payload",
    "render_pdf",
    "write_dossier",
]
