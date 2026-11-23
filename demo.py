import json
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

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


_SAMPLE = Path(__file__).resolve().parent / 'samples' / 'workday.json'


def _handoff(station, issued, receipts, batch, values, parent_id=None):
    model = StationModel(values['A'], values['B'], values['C'], values['D'])
    source = StationSource(tuple(values['state_ids']), values['topology'], tuple(values['raw_rows']))
    revision = revise(station, batch, values['channel'], model, source, parent_id)
    packet = issue_packet(station, issued, revision)
    receipt = accept(receipts, packet.wire, packet.credential)
    return revision, receipt


def _report_result(report):
    return {
        'report_id': report.report_id,
        'status': report.energy_status,
        'energy': str(report.energy) if report.energy is not None else None,
        'verdict': report.verdict,
        'receipts': [source.receipt_id for source in report.sources],
        'revisions': [source.origin.revision_id for source in report.sources],
    }


def run_workday(directory: Path) -> dict:
    values = json.loads(_SAMPLE.read_text(encoding='utf-8'))
    station_path = directory / 'station.sqlite'
    receipt_path = directory / 'receipts.sqlite'
    report_path = directory / 'reports.sqlite'
    batch, station_id, threshold = values['batch'], values['station_id'], values['threshold']
    with closing(ReceiptCatalog(receipt_path)) as receipts, closing(ReportRepository(report_path)) as reports:
        with closing(StationRepository(station_path, station_id)) as station:
            issued = IssuedCatalog(station.connection)
            main_rev, primary = _handoff(station, issued, receipts, batch, values['primary'])
            old_rev, reference = _handoff(station, issued, receipts, batch, values['reference'])
        original = compare(receipts, reports, ReviewRequest(batch, primary, reference, threshold))
        with closing(StationRepository(station_path, station_id)) as station:
            issued = IssuedCatalog(station.connection)
            new_rev, new_reference = _handoff(station, issued, receipts, batch, values['amendment'], old_rev)
        corrected = compare(receipts, reports, ReviewRequest(batch, primary, new_reference, threshold))
    with closing(ReportRepository(report_path)) as reopened:
        signed = [read_report(reopened, report.report_id) for report in (original, corrected)]
        if signed != [original, corrected]:
            raise AssertionError('report snapshots changed on reopening')
        actual = [_report_result(report) for report in signed]
        queue = followup(reopened, values['next_shift'], [report.report_id for report in signed])
    expected = [
        {'report_id': original.report_id, 'status': 'finite', 'energy': '1', 'verdict': 'release',
         'receipts': [primary, reference], 'revisions': [main_rev, old_rev]},
        {'report_id': corrected.report_id, 'status': 'divergent', 'energy': None, 'verdict': 'retest',
         'receipts': [primary, new_reference], 'revisions': [main_rev, new_rev]},
    ]
    followup_expected = [corrected.report_id]
    followup_actual = [item.report_id for item in queue]
    if actual != expected or followup_actual != followup_expected:
        raise AssertionError(f'workday report or followup mismatch: {actual!r}, {followup_actual!r}')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'v8',
        'input': {'batch': batch, 'threshold': threshold,
                  'models': [{key: values[name][key] for key in ('A', 'B', 'C', 'D')}
                             for name in ('primary', 'reference', 'amendment')]},
        'expected': expected,
        'actual': actual,
        'downstream_expected': followup_expected,
        'downstream_actual': followup_actual,
        'code_paths': ['station/revisions.py', 'exchange/issue.py', 'receiving/intake.py',
                       'review/request.py', 'reports/history.py', 'reports/followup.py'],
        'oracle': 'Original tails cancel and the zero-tick difference is 1. Corrected tail is -1,-2,-4,…, so only its report requires retesting.',
    }, ensure_ascii=False, sort_keys=True))
    return {'reports': actual, 'followup': followup_actual}


if __name__ == '__main__':
    with TemporaryDirectory() as directory:
        run_workday(Path(directory))
