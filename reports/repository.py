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
