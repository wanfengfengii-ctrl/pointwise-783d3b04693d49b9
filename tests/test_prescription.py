import sqlite3
from fractions import Fraction

from reports.followup import collect_prescription
from reports.history import read_prescription
from review.prescription import PrescriptionRequest
from review.request import prescribe
from station.models import StationModel
from tests import LabCase, scalar


def two_pole_primary():
    return StationModel(((2, 0), (0, '1/2')), (1, 1), (2, 1), 1)


def unit_pole_reference():
    return scalar(2, 2, 1)


class PrescriptionTests(LabCase):
    def _prescribe(self, pair, max_order, c0, threshold, *, batch='B-01'):
        return prescribe(self.receipts, self.reports,
                         PrescriptionRequest(batch, *pair, max_order, c0, threshold))

    def _counts(self):
        connection = self.reports.connection
        return (connection.execute('SELECT count(*) FROM prescriptions').fetchone()[0],
                connection.execute('SELECT count(*) FROM prescription_sources').fetchone()[0])

    def test_first_order_over_threshold_then_second_order_executable(self):
        pair = self.pair(two_pole_primary(), unit_pole_reference())
        self.station.close()
        first = self._prescribe(pair, 1, 1, '1/3')
        self.assertEqual((first.status, first.energy, first.coefficients),
                         ('over_threshold', Fraction(4, 3), None))
        second = self._prescribe(pair, 2, 1, '1/3')
        self.assertEqual(second.status, 'executable')
        self.assertEqual(second.energy, Fraction(1, 3))
        self.assertEqual(second.coefficients, (Fraction(1), Fraction(1), Fraction(-2)))
        self.assertEqual(second.request.c0, Fraction(1))
        self.assertEqual(second.request.threshold, Fraction(1, 3))
        self.assertEqual(tuple(source.receipt_id for source in second.sources), pair)
        self.assertEqual(second.prescription_id, 2)
        self.assertEqual(read_prescription(self.reports, second.prescription_id), second)
        self.assertEqual(collect_prescription(self.reports, second.prescription_id),
                         second.coefficients)
        self.assertIsNone(collect_prescription(self.reports, first.prescription_id))

    def test_threshold_is_inclusive(self):
        pair = self.pair(two_pole_primary(), unit_pole_reference())
        self.station.close()
        exact = self._prescribe(pair, 2, 1, '1/3')
        below = self._prescribe(pair, 2, 1, '333/1000')
        self.assertEqual(exact.status, 'executable')
        self.assertEqual(below.status, 'over_threshold')
        self.assertEqual(below.energy, Fraction(1, 3))
        self.assertIsNone(below.coefficients)

    def test_repeated_pole_elimination(self):
        primary = scalar(0, 0)
        reference = StationModel(((2, 1), (0, 2)), (0, 1), (4, 4), 1)
        pair = self.pair(primary, reference)
        self.station.close()
        infeasible = self._prescribe(pair, 1, 1, 1)
        self.assertEqual((infeasible.status, infeasible.energy, infeasible.coefficients),
                         ('no_finite', None, None))
        feasible = self._prescribe(pair, 2, 1, 1)
        self.assertEqual((feasible.status, feasible.energy), ('executable', Fraction(1)))
        self.assertEqual(feasible.coefficients, (Fraction(1), Fraction(-4), Fraction(4)))

    def test_zero_reference_keeps_fixed_first_term(self):
        primary = StationModel(((0, 0), (1, 0)), (1, 0), (0, -1), 0)
        reference = scalar(3, 0, 0)
        pair = self.pair(primary, reference)
        self.station.close()
        result = self._prescribe(pair, 3, '-3/2', 1)
        self.assertEqual((result.status, result.energy), ('executable', Fraction(1)))
        self.assertEqual(result.coefficients,
                         (Fraction(-3, 2), Fraction(0), Fraction(0), Fraction(0)))
        self.assertEqual(len(result.coefficients), 4)

    def test_outside_pole_is_rejected_even_if_it_cancels(self):
        same = scalar(3, 3, 1)
        pair = self.pair(same, same)
        self.station.close()
        before = self._counts()
        for max_order in (0, 3):
            with self.subTest(max_order=max_order), self.assertRaises(ValueError):
                self._prescribe(pair, max_order, 1, 100)
        self.assertEqual(self._counts(), before)

    def test_invalid_requests_do_not_sign(self):
        pair = self.pair(two_pole_primary(), unit_pole_reference())
        self.station.close()
        before = self._counts()
        invalid = [(0, 1, -1), (3, 1, -1), (4, 1, 1), (True, 1, 1), (1.0, 1, 1),
                   (1, True, 1), (1, None, 1), (1, '1/0', 1), (1, 1, None), (1, 1, True)]
        for max_order, c0, threshold in invalid:
            with self.subTest(max_order=max_order, c0=c0, threshold=threshold):
                with self.assertRaises(ValueError):
                    self._prescribe(pair, max_order, c0, threshold)
        with self.assertRaises(ValueError):
            prescribe(self.receipts, self.reports, ('B-01', *pair, 1, 1, 1))
        with self.assertRaises(KeyError):
            self._prescribe((pair[0], 999), 1, 1, 1)
        self.assertEqual(self._counts(), before)

    def test_cross_batch_pair_rejected(self):
        pair = self.pair(two_pole_primary(), unit_pole_reference())
        self.station.close()
        before = self._counts()
        with self.assertRaises(ValueError):
            self._prescribe(pair, 1, 1, 1, batch='B-02')
        self.assertEqual(self._counts(), before)

    def test_order_and_provenance_are_preserved(self):
        pair = self.pair(two_pole_primary(), unit_pole_reference())
        self.station.close()
        forward = self._prescribe(pair, 2, 1, '1/3')
        reverse = self._prescribe((pair[1], pair[0]), 2, 1, '1/3')
        self.assertEqual(tuple(source.receipt_id for source in forward.sources), pair)
        self.assertEqual(tuple(source.receipt_id for source in reverse.sources), pair[::-1])
        self.assertEqual(tuple(source.origin.channel for source in forward.sources),
                         ('primary', 'reference'))
        self.assertEqual(tuple(source.origin.channel for source in reverse.sources),
                         ('reference', 'primary'))
        self.assertNotEqual((forward.status, forward.energy),
                            (reverse.status, reverse.energy))

    def test_reopen_reports_only(self):
        pair = self.pair(two_pole_primary(), unit_pole_reference())
        self.station.close()
        over = self._prescribe(pair, 1, 1, '1/3')
        executable = self._prescribe(pair, 2, 1, '1/3')
        self.receipts.close()
        self.reports.close()
        self.reports = self.open_reports()
        self.assertEqual(read_prescription(self.reports, over.prescription_id), over)
        self.assertEqual(read_prescription(self.reports, executable.prescription_id), executable)
        self.assertEqual(collect_prescription(self.reports, executable.prescription_id),
                         executable.coefficients)
        self.assertIsNone(collect_prescription(self.reports, over.prescription_id))

    def test_read_prescription_unknown(self):
        with self.assertRaises(KeyError):
            read_prescription(self.reports, 999)
        with self.assertRaises(KeyError):
            collect_prescription(self.reports, 999)
        for bad in (0, -1, '1', True, 2**63):
            with self.subTest(bad=bad), self.assertRaises(KeyError):
                read_prescription(self.reports, bad)

    def test_commit_failure_leaves_no_draft(self):
        pair = self.pair(two_pole_primary(), unit_pole_reference())
        self.station.close()
        signed = self._prescribe(pair, 1, 1, '1/3')
        original = read_prescription(self.reports, signed.prescription_id)
        self.reports.connection.executescript('''
            CREATE TABLE allowed_commit(id INTEGER PRIMARY KEY);
            CREATE TABLE commit_gate(required INTEGER REFERENCES allowed_commit(id)
                                    DEFERRABLE INITIALLY DEFERRED);
            CREATE TRIGGER fail_prescription_commit AFTER INSERT ON prescription_sources
            WHEN NEW.slot = 1
            BEGIN
                INSERT INTO commit_gate VALUES (1);
            END;
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY'):
            self._prescribe(pair, 2, 1, '1/3')
        self.assertFalse(self.reports.connection.in_transaction)
        self.assertEqual(self._counts(), (1, 2))
        self.assertEqual(self.reports.connection.execute(
            'SELECT count(*) FROM commit_gate').fetchone()[0], 0)
        self.reports.connection.execute('DROP TRIGGER fail_prescription_commit')
        recovered = self._prescribe(pair, 2, 1, '1/3')
        self.assertEqual(recovered.status, 'executable')
        self.reports.close()
        self.reports = self.open_reports()
        self.assertEqual(read_prescription(self.reports, original.prescription_id), original)
        self.assertEqual(read_prescription(self.reports, recovered.prescription_id), recovered)
        self.assertEqual(self._counts(), (2, 4))

    def test_amendment_switches_to_no_finite(self):
        primary_revision = self.freeze('primary', two_pole_primary())
        reference_revision = self.freeze('reference', scalar(2, 2, 1))
        _, primary = self.receive(primary_revision)
        _, reference = self.receive(reference_revision)
        amended_revision = self.freeze('reference', scalar('1/2', '1/2'), parent_id=reference_revision)
        _, amended = self.receive(amended_revision)
        self.station.close()
        feasible = self._prescribe((primary, reference), 2, 1, '1/3')
        self.assertEqual(feasible.status, 'executable')
        infeasible = self._prescribe((primary, amended), 2, 1, '1/3')
        self.assertEqual((infeasible.status, infeasible.energy, infeasible.coefficients),
                         ('no_finite', None, None))
        self.assertEqual(read_prescription(self.reports, feasible.prescription_id), feasible)
