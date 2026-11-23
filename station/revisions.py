from station.models import FrozenRevision, StationModel, StationSource
from station.repository import StationRepository
from station.validation import validate_label, validate_model, validate_parent, validate_source


def revise(station: StationRepository, batch: str, channel: str, model: StationModel,
           source: StationSource, parent_id: int | None = None) -> int:
    batch = validate_label(batch, 'batch')
    channel = validate_label(channel, 'channel')
    model = validate_model(model)
    source = validate_source(source, len(model.A))
    if parent_id is not None:
        validate_parent(read_revision(station, parent_id), batch, channel)
    return station.insert_revision(batch, channel, model, source, parent_id)


def read_revision(station: StationRepository, revision_id: int) -> FrozenRevision:
    revision = station.get_revision(revision_id)
    if revision is None:
        raise KeyError(revision_id)
    return revision
