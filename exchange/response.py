from fractions import Fraction

from exchange.evidence import ResponseEvidence
from exchange.polynomials import multiply_polynomials, reduce_rational
from station.models import StationModel
from station.validation import validate_model


def _matrix_product(left, right):
    columns = tuple(zip(*right))
    return tuple(
        tuple(sum(a * b for a, b in zip(row, column)) for column in columns)
        for row in left
    )


def _determinant_coefficients(matrix):
    """Return det(I - qA) by the Faddeev–LeVerrier trace recurrence."""
    size = len(matrix)
    work = tuple(tuple(Fraction(i == j) for j in range(size)) for i in range(size))
    coefficients = [Fraction(1)]
    for step in range(1, size + 1):
        advanced = _matrix_product(matrix, work)
        coefficient = -sum(advanced[i][i] for i in range(size)) / step
        coefficients.append(coefficient)
        work = tuple(
            tuple(value + (coefficient if i == j else 0) for j, value in enumerate(row))
            for i, row in enumerate(advanced)
        )
    return tuple(coefficients)


def build_response(model: StationModel) -> ResponseEvidence:
    model = validate_model(model)
    denominator = _determinant_coefficients(model.A)
    states = model.B
    tail = []
    for _ in model.A:
        tail.append(sum(coefficient * value for coefficient, value in zip(model.C, states)))
        states = tuple(sum(a * b for a, b in zip(row, states)) for row in model.A)
    # Cayley–Hamilton makes every coefficient at q**size or above vanish.
    numerator = multiply_polynomials(denominator, tail)[:len(model.A)]
    numerator, denominator = reduce_rational(numerator, denominator)
    return ResponseEvidence(model.D, numerator, denominator)
