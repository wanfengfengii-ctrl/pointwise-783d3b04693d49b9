import json
import sqlite3
from fractions import Fraction

from station.models import FrozenRevision, StationModel, StationSource
from station.validation import validate_label


_SCHEMA = '''
CREATE TABLE IF NOT EXISTS station_identity (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    station_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions (
    revision_id INTEGER PRIMARY KEY,
    batch TEXT NOT NULL,
    channel TEXT NOT NULL,
    model TEXT NOT NULL,
    source TEXT NOT NULL,
    parent_id INTEGER REFERENCES revisions(revision_id)
);
'''


def _encode_model(model):
    return json.dumps({
        'A': [[str(value) for value in row] for row in model.A],
        'B': [str(value) for value in model.B],
        'C': [str(value) for value in model.C],
        'D': str(model.D),
        'initial_state': [str(value) for value in model.initial_state],
    })


def _decode_model(text):
    value = json.loads(text)
    return StationModel(
        tuple(tuple(Fraction(entry) for entry in row) for row in value['A']),
        tuple(map(Fraction, value['B'])),
        tuple(map(Fraction, value['C'])),
        Fraction(value['D']),
        tuple(map(Fraction, value['initial_state'])),
    )


class StationRepository:
    def __init__(self, path, station_id: str):
        self.station_id = validate_label(station_id, 'station identity')
        self.connection = sqlite3.connect(path)
        try:
            self.connection.execute('PRAGMA foreign_keys = ON')
            self.connection.executescript(_SCHEMA)
            with self.connection:
                self.connection.execute(
                    'INSERT INTO station_identity VALUES (1, ?) ON CONFLICT(singleton) DO NOTHING',
                    (self.station_id,),
                )
                stored = self.connection.execute('SELECT station_id FROM station_identity').fetchone()[0]
                if stored != self.station_id:
                    raise ValueError('station identity does not match the existing ledger')
        except BaseException:
            self.close()
            raise

    def close(self):
        self.connection.close()

    def insert_revision(self, batch: str, channel: str, model: StationModel,
                        source: StationSource, parent_id: int | None) -> int:
        source_text = json.dumps({
            'state_ids': source.state_ids,
            'topology': source.topology,
            'raw_rows': source.raw_rows,
        }, ensure_ascii=False)
        with self.connection:
            cursor = self.connection.execute(
                'INSERT INTO revisions(batch, channel, model, source, parent_id) VALUES (?, ?, ?, ?, ?)',
                (batch, channel, _encode_model(model), source_text, parent_id),
            )
            revision_id = cursor.lastrowid
        return revision_id

    def get_revision(self, revision_id: int) -> FrozenRevision | None:
        if type(revision_id) is not int or not 0 < revision_id < 2**63:
            return None
        row = self.connection.execute(
            'SELECT batch, channel, model, source, parent_id FROM revisions WHERE revision_id = ?',
            (revision_id,),
        ).fetchone()
        if row is None:
            return None
        batch, channel, model, source, parent_id = row
        raw_source = json.loads(source)
        return FrozenRevision(
            revision_id, batch, channel, _decode_model(model),
            StationSource(tuple(raw_source['state_ids']), raw_source['topology'], tuple(raw_source['raw_rows'])),
            parent_id,
        )
