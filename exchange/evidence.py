from dataclasses import dataclass
from fractions import Fraction

from exchange.polynomials import parse_rational, reduce_rational


@dataclass(frozen=True)
class ResponseEvidence:
    direct: Fraction
    numerator: tuple[Fraction, ...]
    denominator: tuple[Fraction, ...]


def encode_evidence(evidence: ResponseEvidence) -> dict:
    return {
        'direct': str(evidence.direct),
        'numerator': [str(value) for value in evidence.numerator],
        'denominator': [str(value) for value in evidence.denominator],
    }


def _wire_coefficient(text):
    if not isinstance(text, str):
        raise ValueError('wire coefficients must be strings')
    value = parse_rational(text)
    if str(value) != text:
        raise ValueError('wire coefficient is not canonical')
    return value


def _wire_polynomial(values, max_terms):
    if not isinstance(values, list) or not 1 <= len(values) <= max_terms:
        raise ValueError('invalid V1 pulse polynomial size')
    return tuple(_wire_coefficient(value) for value in values)


def decode_evidence(raw: dict) -> ResponseEvidence:
    if not isinstance(raw, dict) or set(raw) != {'direct', 'numerator', 'denominator'}:
        raise ValueError('invalid V1 response body')
    direct = _wire_coefficient(raw['direct'])
    numerator = _wire_polynomial(raw['numerator'], 4)
    denominator = _wire_polynomial(raw['denominator'], 5)
    if reduce_rational(numerator, denominator) != (numerator, denominator):
        raise ValueError('tail must be reduced with denominator constant one')
    return ResponseEvidence(direct, numerator, denominator)
