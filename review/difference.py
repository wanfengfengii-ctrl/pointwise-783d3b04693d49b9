from dataclasses import dataclass
from fractions import Fraction

from exchange.evidence import ResponseEvidence
from exchange.polynomials import multiply_polynomials, reduce_rational, subtract_polynomials


@dataclass(frozen=True)
class DifferenceResponse:
    direct: Fraction
    numerator: tuple[Fraction, ...]
    denominator: tuple[Fraction, ...]


def compose_difference(primary: ResponseEvidence, reference: ResponseEvidence) -> DifferenceResponse:
    left = multiply_polynomials(primary.numerator, reference.denominator)
    right = multiply_polynomials(reference.numerator, primary.denominator)
    numerator = subtract_polynomials(left, right)
    denominator = multiply_polynomials(primary.denominator, reference.denominator)
    numerator, denominator = reduce_rational(numerator, denominator)
    return DifferenceResponse(primary.direct - reference.direct, numerator, denominator)
