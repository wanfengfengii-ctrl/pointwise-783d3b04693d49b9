import sqlite3
from dataclasses import dataclass

from exchange.envelope import unpack_v1
from exchange.provenance import IssueCredential


@dataclass(frozen=True)
class IssuedPacket:
    wire: bytes
    credential: IssueCredential


class IssuedCatalog:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        with connection:
            connection.execute('''
                CREATE TABLE IF NOT EXISTS issued_packets (
                    revision_id INTEGER PRIMARY KEY REFERENCES revisions(revision_id),
                    issue_id TEXT NOT NULL UNIQUE,
                    wire BLOB NOT NULL
                )
            ''')

    def find_by_revision(self, revision_id: int) -> IssuedPacket | None:
        row = self.connection.execute(
            'SELECT issue_id, wire FROM issued_packets WHERE revision_id = ?', (revision_id,)
        ).fetchone()
        if row is None:
            return None
        issue_id, wire = row
        packet = unpack_v1(wire)
        if packet.issue_id != issue_id or packet.origin.revision_id != revision_id:
            raise sqlite3.DatabaseError('issued packet does not match the ledger')
        return IssuedPacket(wire, packet.credential)

    def register_once(self, revision_id: int, wire: bytes) -> IssuedPacket:
        packet = unpack_v1(wire)
        if packet.origin.revision_id != revision_id:
            raise ValueError('issuance revision mismatch')
        with self.connection:
            self.connection.execute('''
                INSERT INTO issued_packets(revision_id, issue_id, wire) VALUES (?, ?, ?)
                ON CONFLICT(revision_id) DO NOTHING
            ''', (revision_id, packet.issue_id, wire))
            stored = self.find_by_revision(revision_id)
            if stored is None:
                raise sqlite3.DatabaseError('issuance was not registered')
        return stored
