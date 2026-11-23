from fractions import Fraction

from receiving.receipt import ReceiptOrigin
from reports.repository import ReportRepository, ReportSource, SignedReport
from review.energy import EnergyResult
from review.verdict import Verdict


def publish_report(repository: ReportRepository, batch: str, threshold: Fraction, result: EnergyResult,
                   verdict: Verdict, sources: tuple[ReceiptOrigin, ReceiptOrigin]) -> SignedReport:
    snapshots = tuple(ReportSource(source.receipt_id, source.issue_id, source.digest, source.origin)
                      for source in sources)
    return repository.commit_report(batch, threshold, result.energy, verdict.value, snapshots)
