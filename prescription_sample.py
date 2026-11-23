import json
import sqlite3
from contextlib import closing
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

from exchange.issue import issue_packet
from exchange.issued_catalog import IssuedCatalog
from receiving.catalog import ReceiptCatalog
from receiving.intake import accept
from reports.followup import collect_prescription, followup
from reports.history import read_prescription, read_report
from reports.repository import ReportRepository, ReportSource
from review.prescription import PrescriptionRequest
from review.request import ReviewRequest, compare, prescribe
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


def _counts(reports):
    connection = reports.connection
    return (connection.execute("SELECT count(*) FROM prescriptions").fetchone()[0],
            connection.execute("SELECT count(*) FROM prescription_sources").fetchone()[0])


def _check_prescription(case, values, prescription, pair):
    wanted = (values["status"], values["energy"],
              None if values["coefficients"] is None else tuple(values["coefficients"]))
    actual = (prescription.status,
              None if prescription.energy is None else str(prescription.energy),
              None if prescription.coefficients is None
              else tuple(str(value) for value in prescription.coefficients))
    if actual != wanted:
        raise AssertionError((case["batch"], values["max_order"], actual, wanted))
    if tuple(source.receipt_id for source in prescription.sources) != (pair[0][1], pair[1][1]):
        raise AssertionError((case["batch"], "source order mismatch"))


def verify_prescriptions(cases):
    signed = []
    with TemporaryDirectory() as directory:
        station_path = Path(directory) / "station.sqlite"
        receipt_path = Path(directory) / "receipts.sqlite"
        report_path = Path(directory) / "reports.sqlite"
        with closing(ReceiptCatalog(receipt_path)) as receipts:
            with closing(StationRepository(station_path, "ql-prescription-sample")) as station:
                pairs = [receive_pair(station, receipts, case) for case in cases]
                with closing(ReportRepository(report_path)) as reports:
                    for case, pair in zip(cases, pairs):
                        for values in case["requests"]:
                            request = PrescriptionRequest(case["batch"], pair[0][1], pair[1][1],
                                                          values["max_order"], values["c0"],
                                                          values["threshold"])
                            if "error" in values:
                                error = {"ValueError": ValueError, "KeyError": KeyError}[values["error"]]
                                before = _counts(reports)
                                try:
                                    prescribe(receipts, reports, request)
                                except error:
                                    pass
                                else:
                                    raise AssertionError((case["batch"], "rejection was missed"))
                                if _counts(reports) != before:
                                    raise AssertionError((case["batch"], "rejected request was stored"))
                                continue
                            prescription = prescribe(receipts, reports, request)
                            _check_prescription(case, values, prescription, pair)
                            normalized = PrescriptionRequest(
                                case["batch"], pair[0][1], pair[1][1], values["max_order"],
                                Fraction(values["c0"]), Fraction(values["threshold"]))
                            if prescription.request != normalized:
                                raise AssertionError((case["batch"], "request was not preserved"))
                            signed.append((case, pair, prescription))
                    for _, _, prescription in signed:
                        if read_prescription(reports, prescription.prescription_id) != prescription:
                            raise AssertionError("prescription snapshot mismatch")
                        coefficients = collect_prescription(reports, prescription.prescription_id)
                        if prescription.status == "executable":
                            if coefficients != prescription.coefficients:
                                raise AssertionError("delivered coefficients mismatch")
                        elif coefficients is not None:
                            raise AssertionError("a non-executable prescription delivered coefficients")
                    amendment_case = next((index, case) for index, case in enumerate(cases)
                                          if "amendment" in case)
                    index, case = amendment_case
                    amended = receive_model(station, receipts, case["batch"], "reference",
                                            case["amendment"], parent_id=pairs[index][1][0])
                    amended_request = PrescriptionRequest(case["batch"], pairs[index][0][1],
                                                          amended[1], 2, 1, "1/3")
                    amended_result = prescribe(receipts, reports, amended_request)
                    if (amended_result.status, amended_result.energy,
                            amended_result.coefficients) != ("no_finite", None, None):
                        raise AssertionError(("amended reference", amended_result.status))
            # The station and receipt ledgers are now closed; the report ledger replays alone.
        with closing(ReportRepository(report_path)) as reopened:
            for _, _, prescription in signed:
                if read_prescription(reopened, prescription.prescription_id) != prescription:
                    raise AssertionError("prescription changed on reopening")
    for case, _, prescription in signed:
        print(f"{case['batch']}: prescription {prescription.prescription_id} "
              f"status={prescription.status} energy={prescription.energy} "
              f"coefficients={prescription.coefficients}")
    return signed


def verify_commit_failure():
    """A failed prescription commit leaves neither a draft nor orphan sources."""
    with TemporaryDirectory() as directory:
        report_path = Path(directory) / "reports.sqlite"
        with closing(ReportRepository(report_path)) as reports:
            connection = reports.connection
            connection.executescript("""
                CREATE TABLE allowed_commit(id INTEGER PRIMARY KEY);
                CREATE TABLE commit_gate(required INTEGER REFERENCES allowed_commit(id)
                                        DEFERRABLE INITIALLY DEFERRED);
                CREATE TRIGGER fail_prescription_commit AFTER INSERT ON prescription_sources
                WHEN NEW.slot = 1 BEGIN INSERT INTO commit_gate VALUES (1); END;
            """)
            request = PrescriptionRequest("QL-FAIL", 1, 2, 1, 1, 1)
            sources = tuple(ReportSource(1 + slot, f"site:{1 + slot}", "0" * 64, _origin())
                            for slot in range(2))
            before = _counts(reports)
            try:
                reports.commit_prescription(request, sources, "over_threshold", Fraction(4, 3), None)
            except sqlite3.IntegrityError:
                pass
            else:
                raise AssertionError("the deferred failure was not raised")
            if _counts(reports) != before:
                raise AssertionError("a failed prescription left a draft")
        with closing(ReportRepository(report_path)) as reopened:
            if reopened.connection.execute("SELECT count(*) FROM prescriptions").fetchone()[0]:
                raise AssertionError("a failed prescription survived reopening")


def _origin():
    from exchange.provenance import IssueOrigin

    return IssueOrigin("ql-sample", "QL-FAIL", "primary", 1, "revision/1")


if __name__ == "__main__":
    cases = load_cases()
    verify_v1(cases)
    verify_prescriptions(cases)
    verify_commit_failure()
    print("commit failure: no draft left behind")
