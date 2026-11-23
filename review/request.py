from dataclasses import dataclass
from fractions import Fraction

from exchange.envelope import unpack_v1
from exchange.polynomials import parse_rational
from receiving.catalog import ReceiptCatalog
from receiving.receipt import Receipt
from reports.publish import publish_report
from reports.repository import ReportRepository, ReportSource, SignedReport
from review.compensation import optimize
from review.difference import compose_difference
from review.energy import compute_energy
from review.prescription import (EXECUTABLE, NO_FINITE, OVER_THRESHOLD,
                                 PrescriptionRequest, SignedPrescription)
from review.verdict import decide_verdict


@dataclass(frozen=True)
class ReviewRequest:
    batch: str
    primary_receipt: int
    reference_receipt: int
    threshold: object


def _evidence_for_batch(receipt: Receipt, batch: str):
    packet = unpack_v1(receipt.wire)
    source = receipt.source
    if (packet.issue_id, packet.digest, packet.origin) != (source.issue_id, source.digest, source.origin):
        raise ValueError('received packet and receipt origin do not match')
    if source.origin.batch != batch:
        raise ValueError('both receipts must belong to the requested batch')
    return packet.evidence


def _validate_request(request) -> tuple[str, int, Fraction, Fraction]:
    if not isinstance(request, PrescriptionRequest):
        raise ValueError('a PrescriptionRequest is required')
    batch = request.batch
    if not isinstance(batch, str) or not batch or batch != batch.strip():
        raise ValueError('invalid prescription batch')
    if type(request.max_order) is not int or not 0 <= request.max_order <= 3:
        raise ValueError('max_order must be an integer between zero and three')
    c0 = parse_rational(request.c0)
    threshold = parse_rational(request.threshold)
    if threshold < 0:
        raise ValueError('energy threshold must be nonnegative')
    return batch, request.max_order, c0, threshold


def _evidence_for_prescription(receipt: Receipt, batch: str):
    packet = unpack_v1(receipt.wire)
    source = receipt.source
    if (packet.issue_id, packet.digest, packet.origin) != (source.issue_id, source.digest, source.origin):
        raise ValueError('received packet and receipt origin do not match')
    if source.origin.batch != batch:
        raise ValueError('both receipts must belong to the requested batch')
    return packet.evidence


def prescribe(receipts: ReceiptCatalog, reports: ReportRepository,
              request: PrescriptionRequest) -> SignedPrescription:
    batch, max_order, c0, threshold = _validate_request(request)
    primary = receipts.lookup(request.primary_receipt)
    reference = receipts.lookup(request.reference_receipt)
    primary_evidence = _evidence_for_prescription(primary, batch)
    reference_evidence = _evidence_for_prescription(reference, batch)
    result = optimize(primary_evidence, reference_evidence, max_order, c0)
    normalized = PrescriptionRequest(batch, request.primary_receipt, request.reference_receipt,
                                     max_order, c0, threshold)
    sources = tuple(ReportSource(source.receipt_id, source.issue_id, source.digest, source.origin)
                    for source in (primary.source, reference.source))
    if result is None:
        status, energy, coefficients = NO_FINITE, None, None
    else:
        energy, coefficients = result
        if energy <= threshold:
            status = EXECUTABLE
        else:
            status, coefficients = OVER_THRESHOLD, None
    return reports.commit_prescription(normalized, sources, status, energy, coefficients)


def compare(receipts: ReceiptCatalog, reports: ReportRepository, request: ReviewRequest) -> SignedReport:
    if not isinstance(request, ReviewRequest):
        raise ValueError('a ReviewRequest is required')
    batch = request.batch
    if not isinstance(batch, str) or not batch or batch != batch.strip():
        raise ValueError('invalid review batch')
    threshold = parse_rational(request.threshold)
    if threshold < 0:
        raise ValueError('energy threshold must be nonnegative')
    primary = receipts.lookup(request.primary_receipt)
    reference = receipts.lookup(request.reference_receipt)
    difference = compose_difference(_evidence_for_batch(primary, batch), _evidence_for_batch(reference, batch))
    result = compute_energy(difference)
    verdict = decide_verdict(result, threshold)
    return publish_report(reports, batch, threshold, result, verdict, (primary.source, reference.source))
