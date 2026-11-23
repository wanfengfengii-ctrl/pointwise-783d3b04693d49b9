import json
from dataclasses import replace
from fractions import Fraction

from exchange.envelope import pack_v1, unpack_v1
from exchange.issue import issue_packet
from receiving.intake import accept
from station.models import StationModel, StationSource
from station.revisions import read_revision
from tests import LabCase, scalar, scenario


class IntakeTests(LabCase):
    def _counts(self):
        connection = self.station.connection
        return (connection.execute('SELECT count(*) FROM revisions').fetchone()[0],
                connection.execute('SELECT count(*) FROM issued_packets').fetchone()[0])

    def test_reissue_and_receive_same_revision(self):
        revision = self.freeze('primary', scalar('1/2', 2))
        first, receipt_id = self.receive(revision)
        replay, replay_id = self.receive(revision)
        stored = self.receipts.lookup(receipt_id)
        self.assertEqual(replay, first)
        self.assertEqual(replay_id, receipt_id)
        self.assertEqual(stored.wire, first.wire)
        self.assertEqual(stored.source.origin, first.credential.origin)
        self.assertEqual(stored.source.origin.revision_id, revision)
        self.assertEqual(self._counts(), (1, 1))
        self.assertEqual(self.receipts.connection.execute('SELECT count(*) FROM received_packets').fetchone()[0], 1)
        scenario('v1', {'revision': revision, 'deliveries': 2}, {'same_issue': True},
                 {'same_issue': first.credential.issue_id == replay.credential.issue_id},
                 {'receipt_ids': [receipt_id, receipt_id], 'revision': revision},
                 {'receipt_ids': [receipt_id, replay_id], 'revision': stored.source.origin.revision_id},
                 ['exchange/issue.py', 'exchange/issued_catalog.py', 'receiving/intake.py', 'receiving/catalog.py'],
                 'A delivery replay identifies the already recorded revision and must reuse the first receipt.')

    def test_invalid_model_rejected(self):
        with self.assertRaises(ValueError):
            self.freeze('primary', StationModel(((1, 0),), (1,), (1,), 0))
        self.assertEqual(self._counts(), (0, 0))

    def test_exact_input(self):
        for model in (scalar(0, 0, None), scalar('1/0', 0), scalar(True, 0), scalar(0.5, 0),
                      StationModel(((0,),), (0,), (0,), 0, (1,))):
            with self.subTest(model=model), self.assertRaises(ValueError):
                self.freeze('primary', model)
        self.assertEqual(self._counts(), (0, 0))
        revision = self.freeze('primary', scalar(0, 0, '0'))
        issued, receipt_id = self.receive(revision)
        response = unpack_v1(self.receipts.lookup(receipt_id).wire).evidence
        self.assertEqual((response.direct, response.numerator, response.denominator), (0, (0,), (1,)))
        self.assertEqual(issued.credential.origin.revision_id, revision)

    def test_full_signed_response(self):
        source = StationSource(('internal-state',), 'internal-topology', ('internal-measured-row',))
        first = self.freeze('primary', scalar('1/2', -2, -1), source=source)
        second_model = StationModel((('1/2',),), (2,), (-1,), -1)
        second = self.freeze('reference', second_model)
        first_packet, first_receipt = self.receive(first)
        _, second_receipt = self.receive(second)
        self.station.close()
        evidence = unpack_v1(self.receipts.lookup(first_receipt).wire).evidence
        equivalent = unpack_v1(self.receipts.lookup(second_receipt).wire).evidence
        self.assertEqual(evidence, equivalent)
        self.assertEqual(evidence.direct, -1)
        self.assertEqual(evidence.numerator, (-2,))
        self.assertEqual(evidence.denominator, (1, Fraction(-1, 2)))
        tail = [evidence.numerator[0]]
        for _ in range(3):
            tail.append(-evidence.denominator[1] * tail[-1])
        self.assertEqual(tail, [-2, -1, Fraction(-1, 2), Fraction(-1, 4)])
        self.assertNotIn(b'internal-', first_packet.wire)
        self.assertEqual(first_packet.credential.origin.source_ref, f'revision/{first}')

    def test_issue_failure_leaves_no_catalog_entry(self):
        with self.assertRaises(KeyError):
            issue_packet(self.station, self.issued, 100)
        revision = self.freeze('primary', scalar(1, 1))
        # Simulate malformed stored input with real storage, then exercise the issuer.
        connection = self.station.connection
        model = json.loads(connection.execute('SELECT model FROM revisions').fetchone()[0])
        model['B'] = []
        with connection:
            connection.execute('UPDATE revisions SET model = ? WHERE revision_id = ?', (json.dumps(model), revision))
        with self.assertRaises(ValueError):
            issue_packet(self.station, self.issued, revision)
        self.assertIsNone(self.issued.find_by_revision(revision))
        self.assertEqual(self._counts(), (1, 0))

    def test_conflicting_body_rejected(self):
        issued, receipt_id = self.receive(self.freeze('primary', scalar(2, 1, 1)))
        original = self.receipts.lookup(receipt_id)
        raw = json.loads(issued.wire)
        raw['body']['direct'] = '2'
        tampered = json.dumps(raw, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        with self.assertRaisesRegex(ValueError, 'packet digest mismatch'):
            accept(self.receipts, tampered, issued.credential)
        self.assertEqual(self.receipts.lookup(receipt_id), original)

    def test_replay_verified(self):
        issued, receipt_id = self.receive(self.freeze('primary', scalar(2, 1)))
        packet = unpack_v1(issued.wire)
        changed = replace(packet.evidence, numerator=(Fraction(2),))
        new_wire = pack_v1(packet.issue_id, packet.origin, changed)
        new_packet = unpack_v1(new_wire)
        self.assertNotEqual(new_packet.digest, packet.digest)
        with self.assertRaisesRegex(ValueError, 'original issuance credential'):
            accept(self.receipts, new_wire, issued.credential)
        with self.assertRaisesRegex(ValueError, 'different receipt'):
            accept(self.receipts, new_wire, new_packet.credential)
        self.assertEqual(self.receipts.connection.execute('SELECT count(*) FROM received_packets').fetchone()[0], 1)
        self.assertEqual(self.receipts.lookup(receipt_id).wire, issued.wire)

    def test_station_revision_copies_input(self):
        matrix, vector = [[1]], [2]
        source_rows = ['before']
        model = StationModel(matrix, vector, [3], 0)
        revision = self.freeze('primary', model, source=StationSource(raw_rows=source_rows))
        matrix[0][0] = 5
        vector[0] = 7
        source_rows[0] = 'after'
        frozen = read_revision(self.station, revision)
        self.assertEqual(frozen.model.A, ((1,),))
        self.assertEqual(frozen.model.B, (2,))
        self.assertEqual(frozen.source.raw_rows, ('before',))
