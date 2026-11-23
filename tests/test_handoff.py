from exchange.issue import issue_packet
from exchange.issued_catalog import IssuedCatalog
from reports.followup import FollowupItem, followup
from reports.history import read_report
from station.models import StationSource
from station.revisions import read_revision
from tests import LabCase, scalar


class HandoffTests(LabCase):
    def _sign_two_versions(self):
        primary = self.freeze('primary', scalar(2, 1, 1))
        reference = self.freeze('reference', scalar(2, 1))
        main_packet, main_id = self.receive(primary)
        old_packet, old_id = self.receive(reference)
        self.station.close()
        original = self.review((main_id, old_id), 1)
        self.station = self.open_station()
        self.issued = IssuedCatalog(self.station.connection)
        amended = self.freeze('reference', scalar(2, 2), parent_id=reference,
                              source=StationSource(raw_rows=('corrected private row',)))
        amended_packet, amended_id = self.receive(amended)
        self.assertEqual(issue_packet(self.station, self.issued, reference), old_packet)
        self.assertNotEqual(amended_id, old_id)
        self.station.close()
        corrected = self.review((main_id, amended_id), 1)
        for report, packets, receipts in ((original, (main_packet, old_packet), (main_id, old_id)),
                                          (corrected, (main_packet, amended_packet), (main_id, amended_id))):
            self.assertEqual(report.batch, 'B-01')
            self.assertEqual(report.threshold, 1)
            self.assertEqual(tuple(source.receipt_id for source in report.sources), receipts)
            self.assertEqual(tuple(source.origin for source in report.sources),
                             tuple(packet.credential.origin for packet in packets))
            self.assertEqual(tuple(source.issue_id for source in report.sources),
                             tuple(packet.credential.issue_id for packet in packets))
            self.assertEqual(tuple(source.digest for source in report.sources),
                             tuple(packet.credential.digest for packet in packets))
        return original, corrected

    def test_amended_report_and_original_survive_restart(self):
        original, corrected = self._sign_two_versions()
        self.assertEqual((original.energy, original.energy_status, original.verdict), (1, 'finite', 'release'))
        self.assertEqual((corrected.energy, corrected.energy_status, corrected.verdict), (None, 'divergent', 'retest'))
        self.receipts.close()
        self.reports.close()
        self.reports = self.open_reports()
        self.assertEqual(read_report(self.reports, corrected.report_id), corrected)
        self.assertEqual(read_report(self.reports, original.report_id), original)
        self.assertEqual(followup(self.reports, 'day', [corrected.report_id, original.report_id]),
                         (FollowupItem('day', corrected.report_id, 'B-01'),))
        with self.assertRaises(KeyError):
            read_report(self.reports, 999)

    def test_parent_ownership(self):
        primary = self.freeze('primary', scalar(2, 1, 1))
        reference = self.freeze('reference', scalar(2, 1))
        snapshots = [read_revision(self.station, number) for number in (primary, reference)]
        with self.assertRaises(ValueError):
            self.freeze('reference', scalar(2, 2), parent_id=primary)
        with self.assertRaises(ValueError):
            self.freeze('reference', scalar(2, 2), batch='B-02', parent_id=reference)
        with self.assertRaises(KeyError):
            self.freeze('reference', scalar(2, 2), parent_id=999)
        self.assertEqual(self.station.connection.execute('SELECT count(*) FROM revisions').fetchone()[0], 2)
        self.assertEqual([read_revision(self.station, number) for number in (primary, reference)], snapshots)
        amended = self.freeze('reference', scalar(2, 2), parent_id=reference)
        self.assertEqual(read_revision(self.station, amended).parent_id, reference)

    def test_explicit_revision(self):
        original = self.freeze('reference', scalar(2, 1), source=StationSource(raw_rows=('original row',)))
        old_packet, old_receipt = self.receive(original)
        corrected = self.freeze('reference', scalar(2, 2), parent_id=original,
                                source=StationSource(raw_rows=('corrected row',)))
        new_packet, new_receipt = self.receive(corrected)
        replay, replay_receipt = self.receive(original)
        self.assertEqual((replay, replay_receipt), (old_packet, old_receipt))
        self.assertNotEqual(new_receipt, old_receipt)
        self.assertEqual(new_packet.credential.origin.revision_id, corrected)
        previous = read_revision(self.station, original)
        latest = read_revision(self.station, corrected)
        self.assertEqual((previous.model.C, previous.source.raw_rows), ((1,), ('original row',)))
        self.assertEqual((latest.model.C, latest.source.raw_rows, latest.parent_id), ((2,), ('corrected row',), original))

    def test_invalid_handoff(self):
        original, corrected = self._sign_two_versions()
        numbers = [original.report_id, corrected.report_id]
        valid = followup(self.reports, 'day', numbers)
        self.assertEqual(valid, (FollowupItem('day', corrected.report_id, 'B-01'),))
        with self.assertRaises(ValueError):
            followup(self.reports, 'unknown', numbers)
        with self.assertRaises(KeyError):
            followup(self.reports, 'day', [*numbers, 999])
        self.assertEqual(followup(self.reports, 'day', [*numbers, corrected.report_id]), valid)
        self.assertEqual(followup(self.reports, 'day', []), ())
        self.assertEqual(self.report_counts(), (2, 4))
