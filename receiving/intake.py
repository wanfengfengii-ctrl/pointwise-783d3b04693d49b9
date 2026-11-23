from exchange.provenance import IssueCredential
from receiving.catalog import ReceiptCatalog
from receiving.validation import validate_incoming


def accept(receipts: ReceiptCatalog, wire: bytes, credential: IssueCredential) -> int:
    packet = validate_incoming(wire, credential)
    return receipts.store_validated(wire, packet)
