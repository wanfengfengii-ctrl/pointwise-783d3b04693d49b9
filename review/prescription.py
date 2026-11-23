"""Request and result values shared by the prescription ledger."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from reports.repository import ReportSource

NO_FINITE = 'no_finite'
OVER_THRESHOLD = 'over_threshold'
EXECUTABLE = 'executable'
STATUSES = (NO_FINITE, OVER_THRESHOLD, EXECUTABLE)


@dataclass(frozen=True)
class PrescriptionRequest:
    batch: str
    primary_receipt: int
    reference_receipt: int
    max_order: int
    c0: object
    threshold: object


@dataclass(frozen=True)
class SignedPrescription:
    prescription_id: int
    request: PrescriptionRequest
    sources: tuple[ReportSource, ReportSource]
    status: str
    energy: Fraction | None
    coefficients: tuple[Fraction, ...] | None
