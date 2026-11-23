import tempfile
import unittest
from pathlib import Path

from demo import run_workday
from exchange.issued_catalog import IssuedCatalog
from reports.history import read_report
from station.revisions import read_revision
from tests import LabCase, scalar


class WorkdayTests(LabCase):
    def test_workday_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_workday(Path(directory))
        self.assertEqual([(item['status'], item['energy'], item['verdict']) for item in result['reports']],
                         [('finite', '1', 'release'), ('divergent', None, 'retest')])
        self.assertEqual(result['followup'], [result['reports'][1]['report_id']])
        old, new = result['reports']
        self.assertEqual(old['revisions'][0], new['revisions'][0])
        self.assertNotEqual(old['revisions'][1], new['revisions'][1])

    def test_reopen_schema_preserves_revisions_receipts_and_reports(self):
        primary = self.freeze('primary', scalar(2, 1, 1))
        reference = self.freeze('reference', scalar(2, 1))
        corrected = self.freeze('reference', scalar(2, 2), parent_id=reference)
        _, left = self.receive(primary)
        issue, right = self.receive(corrected)
        revision = read_revision(self.station, corrected)
        receipt = self.receipts.lookup(right)
        self.station.close()
        report = self.review((left, right), 1)
        self.receipts.close()
        self.reports.close()
        for _ in range(2):
            station = self.open_station()
            issued = IssuedCatalog(station.connection)
            receipts = self.open_receipts()
            reports = self.open_reports()
            self.assertEqual(read_revision(station, corrected), revision)
            self.assertEqual(read_revision(station, corrected).parent_id, reference)
            self.assertEqual(issued.find_by_revision(corrected), issue)
            self.assertEqual(receipts.lookup(right), receipt)
            self.assertEqual(read_report(reports, report.report_id), report)
            self.assertEqual(station.connection.execute('SELECT count(*) FROM revisions').fetchone()[0], 3)
            self.assertEqual(receipts.connection.execute('SELECT count(*) FROM received_packets').fetchone()[0], 2)
            self.assertEqual(reports.connection.execute('SELECT count(*) FROM signed_reports').fetchone()[0], 1)
            station.close()
            receipts.close()
            reports.close()


if __name__ == '__main__':
    unittest.main()
