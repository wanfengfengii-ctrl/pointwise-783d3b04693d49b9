from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from fractions import Fraction

from exchange.provenance import IssueOrigin, decode_origin, encode_origin


_SCHEMA = '''
CREATE TABLE IF NOT EXISTS signed_reports (
    report_id INTEGER PRIMARY KEY,
    batch TEXT NOT NULL,
    threshold TEXT NOT NULL,
    energy TEXT,
    verdict TEXT NOT NULL CHECK (verdict IN ('release', 'retest')),
    CHECK (energy IS NOT NULL OR verdict = 'retest')
);
CREATE TABLE IF NOT EXISTS report_sources (
    report_id INTEGER NOT NULL REFERENCES signed_reports(report_id),
    slot INTEGER NOT NULL CHECK (slot IN (0, 1)),
    receipt_id INTEGER NOT NULL,
    issue_id TEXT NOT NULL,
    digest TEXT NOT NULL,
    origin TEXT NOT NULL,
    PRIMARY KEY(report_id, slot)
);
CREATE TABLE IF NOT EXISTS prescriptions (
    prescription_id INTEGER PRIMARY KEY,
    batch TEXT NOT NULL,
    primary_receipt INTEGER NOT NULL,
    reference_receipt INTEGER NOT NULL,
    max_order INTEGER NOT NULL CHECK (max_order BETWEEN 0 AND 3),
    c0 TEXT NOT NULL,
    threshold TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('no_finite', 'over_threshold', 'executable')),
    energy TEXT,
    coefficients TEXT,
    CHECK (status <> 'no_finite' OR (energy IS NULL AND coefficients IS NULL)),
    CHECK (status <> 'over_threshold' OR (energy IS NOT NULL AND coefficients IS NULL)),
    CHECK (status <> 'executable' OR (energy IS NOT NULL AND coefficients IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS prescription_sources (
    prescription_id INTEGER NOT NULL REFERENCES prescriptions(prescription_id),
    slot INTEGER NOT NULL CHECK (slot IN (0, 1)),
    receipt_id INTEGER NOT NULL,
    issue_id TEXT NOT NULL,
    digest TEXT NOT NULL,
    origin TEXT NOT NULL,
    PRIMARY KEY(prescription_id, slot)
);
'''


@dataclass(frozen=True)
class ReportSource:
    receipt_id: int
    issue_id: str
    digest: str
    origin: IssueOrigin


@dataclass(frozen=True)
class SignedReport:
    report_id: int
    batch: str
    threshold: Fraction
    energy: Fraction | None
    verdict: str
    sources: tuple[ReportSource, ReportSource]

    @property
    def energy_status(self) -> str:
        return 'divergent' if self.energy is None else 'finite'


class ReportRepository:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        try:
            self.connection.execute('PRAGMA foreign_keys = ON')
            self.connection.executescript(_SCHEMA)
        except BaseException:
            self.close()
            raise

    def close(self):
        self.connection.close()

    def commit_report(self, batch: str, threshold: Fraction, energy: Fraction | None,
                      verdict: str, sources: tuple[ReportSource, ReportSource]) -> SignedReport:
        if len(sources) != 2 or any(source.origin.batch != batch for source in sources):
            raise ValueError('a report needs two ordered sources from its batch')
        energy_text = str(energy) if energy is not None else None
        with self.connection:
            cursor = self.connection.execute('''
                INSERT INTO signed_reports(batch, threshold, energy, verdict) VALUES (?, ?, ?, ?)
            ''', (batch, str(threshold), energy_text, verdict))
            report_id = cursor.lastrowid
            self.connection.executemany('''
                INSERT INTO report_sources(report_id, slot, receipt_id, issue_id, digest, origin)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', ((report_id, slot, source.receipt_id, source.issue_id, source.digest,
                   json.dumps(encode_origin(source.origin), sort_keys=True, ensure_ascii=False))
                  for slot, source in enumerate(sources)))
        return SignedReport(report_id, batch, threshold, energy, verdict, sources)

    def get_report(self, report_id: int) -> SignedReport | None:
        if type(report_id) is not int or not 0 < report_id < 2**63:
            return None
        rows = self.connection.execute('''
            SELECT r.batch, r.threshold, r.energy, r.verdict,
                   s.slot, s.receipt_id, s.issue_id, s.digest, s.origin
            FROM signed_reports AS r LEFT JOIN report_sources AS s ON s.report_id = r.report_id
            WHERE r.report_id = ? ORDER BY s.slot
        ''', (report_id,)).fetchall()
        if not rows:
            return None
        if len(rows) != 2 or [row[4] for row in rows] != [0, 1]:
            raise sqlite3.DatabaseError('signed report has an incomplete source snapshot')
        batch, threshold, energy, verdict = rows[0][:4]
        sources = tuple(ReportSource(receipt_id, issue_id, digest, decode_origin(json.loads(origin)))
                        for _, receipt_id, issue_id, digest, origin in (row[4:] for row in rows))
        return SignedReport(report_id, batch, Fraction(threshold),
                            None if energy is None else Fraction(energy), verdict, sources)

    def get_reports(self, report_ids) -> tuple[SignedReport, ...]:
        reports = []
        for report_id in report_ids:
            report = self.get_report(report_id)
            if report is None:
                raise KeyError(report_id)
            reports.append(report)
        return tuple(reports)

    def commit_prescription(self, request, sources: tuple[ReportSource, ReportSource],
                            status: str, energy: Fraction | None,
                            coefficients: tuple[Fraction, ...] | None) -> SignedPrescription:
        from review.prescription import (EXECUTABLE, NO_FINITE, STATUSES,
                                         PrescriptionRequest, SignedPrescription)

        if not isinstance(request, PrescriptionRequest):
            raise ValueError('a PrescriptionRequest is required')
        if status not in STATUSES:
            raise ValueError('invalid prescription status')
        if len(sources) != 2 or any(source.origin.batch != request.batch for source in sources):
            raise ValueError('a prescription needs two ordered sources from its batch')
        if status == NO_FINITE and (energy is not None or coefficients is not None):
            raise ValueError('a no-finite prescription cannot carry an energy')
        if status != EXECUTABLE and coefficients is not None:
            raise ValueError('only an executable prescription carries coefficients')
        if status == EXECUTABLE and (energy is None or coefficients is None):
            raise ValueError('an executable prescription needs an energy and coefficients')
        if coefficients is not None and len(coefficients) != request.max_order + 1:
            raise ValueError('the prescription must carry one coefficient per order')
        energy_text = None if energy is None else str(energy)
        coefficients_text = None if coefficients is None else json.dumps(
            [str(value) for value in coefficients])
        with self.connection:
            cursor = self.connection.execute('''
                INSERT INTO prescriptions(batch, primary_receipt, reference_receipt, max_order,
                                          c0, threshold, status, energy, coefficients)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (request.batch, request.primary_receipt, request.reference_receipt,
                  request.max_order, str(request.c0), str(request.threshold), status,
                  energy_text, coefficients_text))
            prescription_id = cursor.lastrowid
            self.connection.executemany('''
                INSERT INTO prescription_sources(prescription_id, slot, receipt_id, issue_id, digest, origin)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', ((prescription_id, slot, source.receipt_id, source.issue_id, source.digest,
                   json.dumps(encode_origin(source.origin), sort_keys=True, ensure_ascii=False))
                  for slot, source in enumerate(sources)))
        return SignedPrescription(prescription_id, request, sources, status, energy, coefficients)

    def get_prescription(self, prescription_id: int) -> SignedPrescription | None:
        from review.prescription import PrescriptionRequest, SignedPrescription

        if type(prescription_id) is not int or not 0 < prescription_id < 2**63:
            return None
        rows = self.connection.execute('''
            SELECT p.batch, p.primary_receipt, p.reference_receipt, p.max_order,
                   p.c0, p.threshold, p.status, p.energy, p.coefficients,
                   s.slot, s.receipt_id, s.issue_id, s.digest, s.origin
            FROM prescriptions AS p
            LEFT JOIN prescription_sources AS s ON s.prescription_id = p.prescription_id
            WHERE p.prescription_id = ? ORDER BY s.slot
        ''', (prescription_id,)).fetchall()
        if not rows:
            return None
        if len(rows) != 2 or [row[9] for row in rows] != [0, 1]:
            raise sqlite3.DatabaseError('signed prescription has an incomplete source snapshot')
        batch, primary_receipt, reference_receipt, max_order, c0, threshold, status, \
            energy, coefficients = rows[0][:9]
        sources = tuple(ReportSource(receipt_id, issue_id, digest, decode_origin(json.loads(origin)))
                        for _, receipt_id, issue_id, digest, origin in (row[9:] for row in rows))
        request = PrescriptionRequest(batch, primary_receipt, reference_receipt, max_order,
                                      Fraction(c0), Fraction(threshold))
        return SignedPrescription(
            prescription_id, request, sources, status,
            None if energy is None else Fraction(energy),
            None if coefficients is None else tuple(Fraction(value) for value in json.loads(coefficients)),
        )
