from dataclasses import dataclass

from reports.repository import ReportRepository
from review.verdict import Verdict


@dataclass(frozen=True)
class FollowupItem:
    shift: str
    report_id: int
    batch: str


def followup(repository: ReportRepository, shift: str, report_ids) -> tuple[FollowupItem, ...]:
    if shift not in ('day', 'night'):
        raise ValueError('shift must be day or night')
    if isinstance(report_ids, (str, bytes)):
        raise ValueError('report numbers must be provided as a collection')
    try:
        ids = tuple(report_ids)
    except TypeError as error:
        raise ValueError('report numbers must be provided as a collection') from error
    if any(type(report_id) is not int or not 0 < report_id < 2**63 for report_id in ids):
        raise ValueError('invalid report number in handoff')
    reports = repository.get_reports(sorted(set(ids)))
    return tuple(FollowupItem(shift, report.report_id, report.batch)
                 for report in reports if report.verdict == Verdict.RETEST.value)
