import json
from contextlib import closing
from pathlib import Path

from exchange.issue import issue_packet
from exchange.issued_catalog import IssuedCatalog
from receiving.catalog import ReceiptCatalog
from receiving.intake import accept
from reports.followup import followup
from reports.history import read_report
from reports.repository import ReportRepository
from review.request import ReviewRequest, compare
from station.models import StationModel, StationSource
from station.repository import StationRepository
from station.revisions import revise

_SAMPLE = Path(__file__).resolve().parent / "samples" / "prescription.json"


def load_cases():
    return json.loads(_SAMPLE.read_text(encoding="utf-8"))


def receive_model(station, receipts, batch, channel, values, parent_id=None):
    model = StationModel(values["A"], values["B"], values["C"], values["D"])
    source = StationSource(raw_rows=(f"fixture/{batch}/{channel}",))
    revision = revise(station, batch, channel, model, source, parent_id)
    issued = issue_packet(station, IssuedCatalog(station.connection), revision)
    return revision, accept(receipts, issued.wire, issued.credential)


def receive_pair(station, receipts, case):
    return tuple(receive_model(station, receipts, case["batch"], role, case[role])
                 for role in ("primary", "reference"))


def verify_v1(cases):
    with closing(ReportRepository(":memory:")) as reports:
        signed = []
        with closing(ReceiptCatalog(":memory:")) as receipts:
            with closing(StationRepository(":memory:", "ql-prescription-sample")) as station:
                pairs = [receive_pair(station, receipts, case) for case in cases]
            for case, pair in zip(cases, pairs):
                receipt_ids = tuple(receipt_id for _, receipt_id in pair)
                expected = case["v1"]
                request = ReviewRequest(case["batch"], *receipt_ids, expected["threshold"])
                report = compare(receipts, reports, request)
                energy = str(report.energy) if report.energy is not None else None
                actual = (energy, report.verdict, tuple(source.receipt_id for source in report.sources),
                          tuple(source.origin.revision_id for source in report.sources))
                wanted = (expected["energy"], expected["verdict"], receipt_ids,
                          tuple(revision for revision, _ in pair))
                if actual != wanted:
                    raise AssertionError((case["batch"], actual, wanted))
                signed.append((case["batch"], report))
        for batch, report in signed:
            if read_report(reports, report.report_id) != report:
                raise AssertionError(f"V1 snapshot mismatch for {batch}")
            queue = followup(reports, "day", [report.report_id])
            expected_ids = [report.report_id] if report.verdict == "retest" else []
            if [item.report_id for item in queue] != expected_ids:
                raise AssertionError(f"V1 follow-up mismatch for {batch}")
            print(f"{batch}: V1 energy={report.energy}, verdict={report.verdict}, followup={len(queue)}")


if __name__ == "__main__":
    verify_v1(load_cases())
