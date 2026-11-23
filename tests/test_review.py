import sqlite3
from fractions import Fraction

from reports.followup import followup
from reports.history import read_report
from station.models import StationModel
from tests import LabCase, scalar, scenario


class ReviewTests(LabCase):
    def test_stable_difference_at_limit(self):
        pair = self.pair(scalar('1/2', 2), scalar('1/2', 1))
        self.station.close()
        report = self.review(pair, '4/3')
        self.assertEqual(report.energy, Fraction(4, 3))
        self.assertEqual(report.energy_status, 'finite')
        self.assertEqual(report.verdict, 'release')
        self.assertEqual(read_report(self.reports, report.report_id), report)
        queue = followup(self.reports, 'night', [report.report_id])
        self.assertEqual(queue, ())
        scenario('v4', {'direct': [0, 0], 'first_tail': [2, 1], 'ratio': '1/2', 'threshold': '4/3'},
                 {'energy': '4/3', 'verdict': 'release'},
                 {'energy': str(report.energy), 'verdict': report.verdict}, [], [item.report_id for item in queue],
                 ['review/difference.py', 'review/energy.py', 'review/verdict.py', 'reports/followup.py'],
                 'Squared differences from the first tail term form 1 + 1/4 + 1/16 + … = 4/3.')

    def test_stable_difference_above_limit(self):
        pair = self.pair(scalar('1/2', 2), scalar('1/2', 1))
        self.station.close()
        report = self.review(pair, 1)
        self.assertEqual((report.energy, report.verdict), (Fraction(4, 3), 'retest'))
        self.assertEqual([item.report_id for item in followup(self.reports, 'night', [report.report_id])],
                         [report.report_id])

    def test_shared_unstable_tail_cancels(self):
        pair = self.pair(scalar(2, 1, 1), scalar(2, 1))
        self.station.close()
        report = self.review(pair, 1)
        self.assertEqual((report.energy, report.energy_status, report.verdict), (1, 'finite', 'release'))
        self.assertEqual(tuple(source.receipt_id for source in report.sources), pair)
        queue = followup(self.reports, 'night', [report.report_id])
        self.assertEqual(queue, ())
        scenario('v5', {'direct': [1, 0], 'first_tail': [1, 1], 'ratio': 2, 'threshold': 1},
                 {'energy': '1', 'verdict': 'release'},
                 {'energy': str(report.energy), 'verdict': report.verdict}, [], [item.report_id for item in queue],
                 ['review/request.py', 'review/difference.py', 'review/energy.py', 'reports/followup.py'],
                 'Every tail term matches. The remaining zero-tick difference has square 1.')

    def test_partial_unit_pole(self):
        matrix = ((1, 1), (0, 1))
        pair = self.pair(StationModel(matrix, (0, 1), (1, 1), 0),
                         StationModel(matrix, (0, 1), (1, 0), 0))
        self.station.close()
        report = self.review(pair, 100)
        self.assertEqual((report.energy, report.energy_status, report.verdict), (None, 'divergent', 'retest'))

    def test_zero_difference(self):
        pair = self.pair(scalar(-2, -5, -3), scalar(-2, -5, -3))
        self.station.close()
        report = self.review(pair, 0)
        self.assertIsInstance(report.energy, Fraction)
        self.assertEqual((report.energy, report.energy_status, report.verdict), (0, 'finite', 'release'))

    def test_delayed_tail(self):
        matrix = ((0, 0, 0, 0), (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 1))
        delayed = StationModel(matrix, (1, 0, 0, 0), (0, 0, 0, 1), 0)
        pair = self.pair(delayed, StationModel((), (), (), 0))
        self.station.close()
        report = self.review(pair, 100)
        self.assertEqual((report.energy, report.verdict), (None, 'retest'))

    def test_finite_tail_and_complex_poles(self):
        delay = ((0, 0, 0, 0), (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0))
        finite = self.pair(StationModel(delay, (1, 0, 0, 0), (0, 0, 0, -2), -1),
                           StationModel((), (), (), 0))
        stable = self.pair(StationModel(((0, '-1/4'), (1, 0)), (1, 0), (1, 0), 0),
                           StationModel((), (), (), 0))
        unit_modulus = self.pair(StationModel(((0, -1), (1, 0)), (1, 0), (1, 0), 0),
                                 StationModel((), (), (), 0))
        self.station.close()
        self.assertEqual(self.review(finite, 5).energy, 5)
        self.assertEqual(self.review(stable, '16/15').energy, Fraction(16, 15))
        self.assertIsNone(self.review(unit_modulus, 100).energy)

    def test_cross_batch_pair_rejected(self):
        own_pair = self.pair(scalar(0, 2), scalar(0, 1))
        _, wrong = self.receive(self.freeze('reference', scalar(0, 1), batch='B-02'))
        self.station.close()
        valid = self.review(own_pair, 1)
        for pair in ((own_pair[0], wrong), (wrong, own_pair[1])):
            with self.subTest(pair=pair), self.assertRaises(ValueError):
                self.review(pair, 1)
        self.assertEqual(self.report_counts(), (1, 2))
        self.assertEqual(read_report(self.reports, valid.report_id), valid)

    def test_request_errors(self):
        pair = self.pair(scalar(0, 1), scalar(0, 0))
        self.station.close()
        for threshold in (-1, None, '1/0', True):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                self.review(pair, threshold)
        with self.assertRaises(KeyError):
            self.review((pair[0], 999), 1)
        self.assertEqual(self.report_counts(), (0, 0))

    def test_commit_failure_does_not_publish(self):
        pair = self.pair(scalar(0, 2), scalar(0, 0))
        self.station.close()
        existing = self.review(pair, 1)
        original_queue = followup(self.reports, 'night', [existing.report_id])
        self.assertEqual(len(original_queue), 1)
        # The trigger writes an unresolved deferred reference after both sources are written.
        # The INSERT statements finish; SQLite rejects the transaction at COMMIT.
        self.reports.connection.executescript('''
            CREATE TABLE allowed_commit(id INTEGER PRIMARY KEY);
            CREATE TABLE commit_gate(required INTEGER REFERENCES allowed_commit(id)
                                                    DEFERRABLE INITIALLY DEFERRED);
            CREATE TRIGGER fail_report_commit AFTER INSERT ON report_sources WHEN NEW.slot = 1
            BEGIN
                INSERT INTO commit_gate VALUES (1);
            END;
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY'):
            self.review(pair, 4)
        self.assertFalse(self.reports.connection.in_transaction)
        self.assertEqual(self.report_counts(), (1, 2))
        self.assertEqual(self.reports.connection.execute('SELECT count(*) FROM commit_gate').fetchone()[0], 0)
        self.reports.close()
        self.reports = self.open_reports()
        self.assertEqual(read_report(self.reports, existing.report_id), existing)
        self.assertEqual(followup(self.reports, 'night', [existing.report_id]), original_queue)
        self.assertEqual(self.report_counts(), (1, 2))
