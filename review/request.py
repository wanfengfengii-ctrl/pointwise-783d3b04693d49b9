from dataclasses import dataclass

from exchange.envelope import unpack_v1
from exchange.polynomials import parse_rational
from receiving.catalog import ReceiptCatalog
from receiving.receipt import Receipt
from reports.publish import publish_report
from reports.repository import ReportRepository, SignedReport
from review.difference import compose_difference
from review.energy import compute_energy
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
