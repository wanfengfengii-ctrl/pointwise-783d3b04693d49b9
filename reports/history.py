from reports.repository import ReportRepository, SignedReport


def read_report(repository: ReportRepository, report_id: int) -> SignedReport:
    report = repository.get_report(report_id)
    if report is None:
        raise KeyError(report_id)
    return report
