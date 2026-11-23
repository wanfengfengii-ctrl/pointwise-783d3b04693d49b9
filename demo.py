import json
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
from reports.repository import ReportRepository
from review.prescription import PrescriptionRequest
from review.request import ReviewRequest, compare, prescribe
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


def _prescription_result(prescription):
    return {
        'prescription_id': prescription.prescription_id,
        'status': prescription.status,
        'energy': str(prescription.energy) if prescription.energy is not None else None,
        'coefficients': None if prescription.coefficients is None
        else [str(value) for value in prescription.coefficients],
        'receipts': [source.receipt_id for source in prescription.sources],
        'revisions': [source.origin.revision_id for source in prescription.sources],
    }


def run_workday(directory: Path) -> dict:
    values = json.loads(_SAMPLE.read_text(encoding='utf-8'))
    station_path = directory / 'station.sqlite'
    receipt_path = directory / 'receipts.sqlite'
    report_path = directory / 'reports.sqlite'
    batch, station_id, threshold = values['batch'], values['station_id'], values['threshold']
    incident = values['incident']
    incident_batch = incident['batch']
    with closing(ReceiptCatalog(receipt_path)) as receipts, closing(ReportRepository(report_path)) as reports:
        with closing(StationRepository(station_path, station_id)) as station:
            issued = IssuedCatalog(station.connection)
            main_rev, primary = _handoff(station, issued, receipts, batch, values['primary'])
            old_rev, reference = _handoff(station, issued, receipts, batch, values['reference'])
            incident_main, incident_primary = _handoff(station, issued, receipts,
                                                       incident_batch, incident['primary'])
            incident_reference, incident_reference_receipt = _handoff(
                station, issued, receipts, incident_batch, incident['reference'])
        original = compare(receipts, reports, ReviewRequest(batch, primary, reference, threshold))
        # The station ledger is closed before the night shift signs the prescription.
        prescription = prescribe(receipts, reports, PrescriptionRequest(
            incident_batch, incident_primary, incident_reference_receipt,
            incident['request']['max_order'], incident['request']['c0'],
            incident['request']['threshold']))
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
        delivered = read_prescription(reopened, prescription.prescription_id)
        if delivered != prescription:
            raise AssertionError('prescription snapshot changed on reopening')
        prescription_actual = _prescription_result(delivered)
        prescription_coefficients = collect_prescription(reopened, delivered.prescription_id)
    expected = [
        {'report_id': original.report_id, 'status': 'finite', 'energy': '1', 'verdict': 'release',
         'receipts': [primary, reference], 'revisions': [main_rev, old_rev]},
        {'report_id': corrected.report_id, 'status': 'divergent', 'energy': None, 'verdict': 'retest',
         'receipts': [primary, new_reference], 'revisions': [main_rev, new_rev]},
    ]
    followup_expected = [corrected.report_id]
    followup_actual = [item.report_id for item in queue]
    prescription_expected = {
        'prescription_id': prescription.prescription_id,
        'status': incident['expected']['status'],
        'energy': incident['expected']['energy'],
        'coefficients': incident['expected']['coefficients'],
        'receipts': [incident_primary, incident_reference_receipt],
        'revisions': [incident_main, incident_reference],
    }
    if actual != expected or followup_actual != followup_expected:
        raise AssertionError(f'workday report or followup mismatch: {actual!r}, {followup_actual!r}')
    if prescription_actual != prescription_expected:
        raise AssertionError(f'workday prescription mismatch: {prescription_actual!r}')
    delivered_expected = (None if incident['expected']['coefficients'] is None
                          else tuple(Fraction(value) for value in incident['expected']['coefficients']))
    if prescription_coefficients != delivered_expected:
        raise AssertionError(f'workday delivery mismatch: {prescription_coefficients!r}')
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
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'v9',
        'input': {'batch': incident_batch,
                  'models': [{key: incident[name][key] for key in ('A', 'B', 'C', 'D')}
                             for name in ('primary', 'reference')],
                  'request': incident['request']},
        'expected': prescription_expected,
        'actual': prescription_actual,
        'downstream_expected': [str(value) for value in delivered_expected]
        if delivered_expected is not None else None,
        'downstream_actual': None if prescription_coefficients is None
        else [str(value) for value in prescription_coefficients],
        'code_paths': ['review/compensation.py', 'review/request.py', 'reports/repository.py',
                       'reports/history.py', 'reports/followup.py'],
        'oracle': 'The second-order compensator cancels the shared non-decaying tail and leaves energy 1/3; the report ledger replays it after the station and receipt ledgers close.',
    }, ensure_ascii=False, sort_keys=True))
    return {'reports': actual, 'followup': followup_actual,
            'prescriptions': prescription_actual}


if __name__ == '__main__':
    with TemporaryDirectory() as directory:
        run_workday(Path(directory))
