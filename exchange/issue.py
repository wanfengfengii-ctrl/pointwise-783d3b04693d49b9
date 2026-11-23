from exchange.envelope import pack_v1
from exchange.issued_catalog import IssuedCatalog, IssuedPacket
from exchange.provenance import IssueOrigin, issue_identity
from exchange.response import build_response
from station.repository import StationRepository
from station.revisions import read_revision


def issue_packet(station: StationRepository, issued: IssuedCatalog, revision_id: int) -> IssuedPacket:
    if issued.connection is not station.connection:
        raise ValueError('the issue catalog must use the selected station ledger')
    revision = read_revision(station, revision_id)
    prior = issued.find_by_revision(revision_id)
    if prior is not None:
        return prior
    origin = IssueOrigin(station.station_id, revision.batch, revision.channel,
                         revision_id, f'revision/{revision_id}')
    evidence = build_response(revision.model)
    wire = pack_v1(issue_identity(origin), origin, evidence)
    return issued.register_once(revision_id, wire)
