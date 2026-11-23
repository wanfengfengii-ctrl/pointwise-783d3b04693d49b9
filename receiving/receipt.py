from dataclasses import dataclass

from exchange.provenance import IssueOrigin


@dataclass(frozen=True)
class ReceiptOrigin:
    receipt_id: int
    issue_id: str
    digest: str
    origin: IssueOrigin


@dataclass(frozen=True)
class Receipt:
    wire: bytes
    source: ReceiptOrigin
