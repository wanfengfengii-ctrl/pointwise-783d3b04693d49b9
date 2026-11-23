import json
import tempfile
import unittest
from pathlib import Path

from exchange.issue import issue_packet
from exchange.issued_catalog import IssuedCatalog
from receiving.catalog import ReceiptCatalog
from receiving.intake import accept
from reports.repository import ReportRepository
from review.request import ReviewRequest, compare
from station.models import StationModel, StationSource
from station.repository import StationRepository
from station.revisions import revise


class LabCase(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(directory)
        self.station = self.open_station()
        self.issued = IssuedCatalog(self.station.connection)
        self.receipts = self.open_receipts()
        self.reports = self.open_reports()

    def open_station(self):
        station = StationRepository(self.root / 'station.sqlite', 'lab-test')
        self.addCleanup(station.close)
        return station

    def open_receipts(self):
        receipts = ReceiptCatalog(self.root / 'receipts.sqlite')
        self.addCleanup(receipts.close)
        return receipts

    def open_reports(self):
        reports = ReportRepository(self.root / 'reports.sqlite')
        self.addCleanup(reports.close)
        return reports

    def freeze(self, channel, model, *, batch='B-01', parent_id=None, source=None):
        source = source if source is not None else StationSource(raw_rows=('private-demo-row',))
        return revise(self.station, batch, channel, model, source, parent_id)

    def receive(self, revision):
        issued = issue_packet(self.station, self.issued, revision)
        receipt_id = accept(self.receipts, issued.wire, issued.credential)
        return issued, receipt_id

    def pair(self, primary, reference):
        _, left = self.receive(self.freeze('primary', primary))
        _, right = self.receive(self.freeze('reference', reference))
        return left, right

    def review(self, pair, threshold, *, batch='B-01'):
        return compare(self.receipts, self.reports, ReviewRequest(batch, *pair, threshold))

    def report_counts(self):
        connection = self.reports.connection
        reports = connection.execute('SELECT count(*) FROM signed_reports').fetchone()[0]
        sources = connection.execute('SELECT count(*) FROM report_sources').fetchone()[0]
        return reports, sources


def scalar(a, c, d=0):
    return StationModel(((a,),), (1,), (c,), d)


def scenario(case_id, inputs, expected, actual, downstream_expected, downstream_actual, paths, oracle):
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': case_id,
        'input': inputs,
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': paths,
        'oracle': oracle,
    }, ensure_ascii=False, sort_keys=True))
