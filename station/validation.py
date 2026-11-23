from exchange.polynomials import parse_rational
from station.models import FrozenRevision, StationModel, StationSource


def validate_label(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f'{field} must be a nonempty trimmed string')
    return value


def _vector(values, size):
    if not isinstance(values, (tuple, list)) or len(values) != size:
        raise ValueError('model vector has the wrong size')
    return tuple(parse_rational(value) for value in values)


def validate_model(model: StationModel) -> StationModel:
    if not isinstance(model, StationModel):
        raise ValueError('a StationModel is required')
    if not isinstance(model.A, (tuple, list)) or len(model.A) > 4:
        raise ValueError('A must have zero to four rows')
    size = len(model.A)
    matrix = tuple(_vector(row, size) for row in model.A)
    b = _vector(model.B, size)
    c = _vector(model.C, size)
    direct = parse_rational(model.D)
    initial = model.initial_state if model.initial_state is not None else (0,) * size
    initial = _vector(initial, size)
    if any(initial):
        raise ValueError('the initial state must be zero')
    return StationModel(matrix, b, c, direct, initial)


def validate_source(source: StationSource, size: int) -> StationSource:
    if not isinstance(source, StationSource) or not isinstance(source.topology, str):
        raise ValueError('invalid station source')
    if not isinstance(source.state_ids, (list, tuple)) or not isinstance(source.raw_rows, (list, tuple)):
        raise ValueError('state identifiers and measured rows must be sequences')
    ids = tuple(validate_label(item, 'state identifier') for item in source.state_ids)
    if ids and (len(ids) != size or len(set(ids)) != len(ids)):
        raise ValueError('state identifiers must match the model states')
    if any(not isinstance(row, str) for row in source.raw_rows):
        raise ValueError('station measured rows must be text')
    return StationSource(ids, source.topology, tuple(source.raw_rows))


def validate_parent(parent: FrozenRevision, batch: str, channel: str) -> None:
    if (parent.batch, parent.channel) != (batch, channel):
        raise ValueError('the parent must belong to the same batch and channel')
