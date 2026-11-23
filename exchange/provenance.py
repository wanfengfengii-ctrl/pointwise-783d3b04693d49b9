from dataclasses import dataclass


@dataclass(frozen=True)
class IssueOrigin:
    station_id: str
    batch: str
    channel: str
    revision_id: int
    source_ref: str


@dataclass(frozen=True)
class IssueCredential:
    issue_id: str
    origin: IssueOrigin
    digest: str


def issue_identity(origin: IssueOrigin) -> str:
    return f'{origin.station_id}:{origin.revision_id}'


def encode_origin(origin: IssueOrigin) -> dict:
    return {
        'station_id': origin.station_id,
        'batch': origin.batch,
        'channel': origin.channel,
        'revision_id': origin.revision_id,
        'source_ref': origin.source_ref,
    }


def decode_origin(raw: dict) -> IssueOrigin:
    labels = ('station_id', 'batch', 'channel', 'source_ref')
    if not isinstance(raw, dict) or set(raw) != {*labels, 'revision_id'}:
        raise ValueError('invalid issuance origin')
    for key in labels:
        value = raw[key]
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError(f'invalid origin field {key}')
    revision_id = raw['revision_id']
    if type(revision_id) is not int or not 0 < revision_id < 2**63:
        raise ValueError('invalid origin revision number')
    if raw['source_ref'] != f'revision/{revision_id}':
        raise ValueError('origin reference does not match its revision')
    return IssueOrigin(**raw)
