from exchange.envelope import V1Packet, unpack_v1
from exchange.provenance import IssueCredential


def validate_incoming(wire: bytes, credential: IssueCredential) -> V1Packet:
    packet = unpack_v1(wire)
    if not isinstance(credential, IssueCredential) or packet.credential != credential:
        raise ValueError('packet conflicts with the original issuance credential')
    return packet
