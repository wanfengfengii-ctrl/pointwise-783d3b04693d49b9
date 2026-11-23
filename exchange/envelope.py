import hashlib
import json
from dataclasses import dataclass

from exchange.evidence import ResponseEvidence, decode_evidence, encode_evidence
from exchange.provenance import IssueCredential, IssueOrigin, decode_origin, encode_origin, issue_identity


@dataclass(frozen=True)
class V1Packet:
    issue_id: str
    origin: IssueOrigin
    evidence: ResponseEvidence
    digest: str

    @property
    def credential(self) -> IssueCredential:
        return IssueCredential(self.issue_id, self.origin, self.digest)


def _canonical(document):
    return json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


def _payload(issue_id, origin, evidence):
    return {'version': 1, 'issue_id': issue_id, 'origin': encode_origin(origin),
            'body': encode_evidence(evidence)}


def packet_digest(issue_id: str, origin: IssueOrigin, evidence: ResponseEvidence) -> str:
    return hashlib.sha256(_canonical(_payload(issue_id, origin, evidence))).hexdigest()


def pack_v1(issue_id: str, origin: IssueOrigin, evidence: ResponseEvidence) -> bytes:
    payload = _payload(issue_id, origin, evidence)
    decode_origin(payload['origin'])
    decode_evidence(payload['body'])
    if issue_id != issue_identity(origin):
        raise ValueError('issuance identity does not match its origin')
    return _canonical({**payload, 'digest': packet_digest(issue_id, origin, evidence)})


def unpack_v1(wire: bytes) -> V1Packet:
    if not isinstance(wire, bytes):
        raise ValueError('a V1 packet must be bytes')
    try:
        raw = json.loads(wire.decode('utf-8'))
    except (ValueError, RecursionError) as error:
        raise ValueError('invalid V1 JSON') from error
    if not isinstance(raw, dict) or set(raw) != {'version', 'issue_id', 'origin', 'body', 'digest'}:
        raise ValueError('invalid V1 envelope')
    if type(raw['version']) is not int or raw['version'] != 1:
        raise ValueError('unsupported packet version')
    origin = decode_origin(raw['origin'])
    evidence = decode_evidence(raw['body'])
    issue_id = raw['issue_id']
    if issue_id != issue_identity(origin):
        raise ValueError('issuance identity does not match its origin')
    digest = packet_digest(issue_id, origin, evidence)
    if raw['digest'] != digest:
        raise ValueError('packet digest mismatch')
    if _canonical(raw) != wire:
        raise ValueError('packet is not canonical V1 JSON')
    return V1Packet(issue_id, origin, evidence, digest)
