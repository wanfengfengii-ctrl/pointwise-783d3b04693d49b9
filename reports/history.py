from reports.repository import ReportRepository, SignedReport
from review.prescription import SignedPrescription


def read_report(repository: ReportRepository, report_id: int) -> SignedReport:
    report = repository.get_report(report_id)
    if report is None:
        raise KeyError(report_id)
    return report


def read_prescription(repository: ReportRepository, prescription_id: int) -> SignedPrescription:
    prescription = repository.get_prescription(prescription_id)
    if prescription is None:
        raise KeyError(prescription_id)
    return prescription
