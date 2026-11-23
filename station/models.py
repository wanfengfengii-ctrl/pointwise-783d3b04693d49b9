from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence


RationalInput = int | str | Fraction


@dataclass(frozen=True)
class StationModel:
    A: Sequence[Sequence[RationalInput]]
    B: Sequence[RationalInput]
    C: Sequence[RationalInput]
    D: RationalInput
    initial_state: Sequence[RationalInput] | None = None


@dataclass(frozen=True)
class StationSource:
    state_ids: tuple[str, ...] = ()
    topology: str = ''
    raw_rows: tuple[str, ...] = ()


@dataclass(frozen=True)
class FrozenRevision:
    revision_id: int
    batch: str
    channel: str
    model: StationModel
    source: StationSource
    parent_id: int | None
