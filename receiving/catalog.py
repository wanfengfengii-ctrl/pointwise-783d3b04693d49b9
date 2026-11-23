import json
import sqlite3

from exchange.envelope import V1Packet
from exchange.provenance import decode_origin, encode_origin
from receiving.receipt import Receipt, ReceiptOrigin


_SCHEMA = '''
CREATE TABLE IF NOT EXISTS received_packets (
    receipt_id INTEGER PRIMARY KEY,
    issue_id TEXT NOT NULL UNIQUE,
    digest TEXT NOT NULL,
    origin TEXT NOT NULL,
    wire BLOB NOT NULL
)
'''


class ReceiptCatalog:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)
        try:
            with self.connection:
                self.connection.execute(_SCHEMA)
        except BaseException:
            self.close()
            raise

    def close(self):
        self.connection.close()

    def store_validated(self, wire: bytes, packet: V1Packet) -> int:
        origin = json.dumps(encode_origin(packet.origin), sort_keys=True, ensure_ascii=False)
        with self.connection:
            self.connection.execute('''
                INSERT INTO received_packets(issue_id, digest, origin, wire) VALUES (?, ?, ?, ?)
                ON CONFLICT(issue_id) DO NOTHING
            ''', (packet.issue_id, packet.digest, origin, wire))
            stored = self.connection.execute('''
                SELECT receipt_id, digest, origin, wire FROM received_packets WHERE issue_id = ?
            ''', (packet.issue_id,)).fetchone()
            if stored is None:
                raise sqlite3.DatabaseError('receipt was not registered')
            receipt_id, existing_digest, existing_origin, existing_wire = stored
            if (existing_digest, existing_origin, existing_wire) != (packet.digest, origin, wire):
                raise ValueError('the issuance identity already has a different receipt')
        return receipt_id

    def lookup(self, receipt_id: int) -> Receipt:
        if type(receipt_id) is not int or not 0 < receipt_id < 2**63:
            raise KeyError(receipt_id)
        row = self.connection.execute('''
            SELECT issue_id, digest, origin, wire FROM received_packets WHERE receipt_id = ?
        ''', (receipt_id,)).fetchone()
        if row is None:
            raise KeyError(receipt_id)
        issue_id, digest, origin, wire = row
        return Receipt(wire, ReceiptOrigin(receipt_id, issue_id, digest, decode_origin(json.loads(origin))))
