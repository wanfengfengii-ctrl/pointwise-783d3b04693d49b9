"""Exact delay-compensation arithmetic for signing prescriptions.

A fixed piece stores ``direct + q * numerator / denominator``.  A prescription
``F(q) = c0 + c1 q + ... + cK q**K`` is applied to the reference piece and the
residual ``P - F*R`` is scored by the squared sum of all ticks from tick zero.

The module works with exact rational polynomials in q.  Non-decaying visible
poles of a single piece may only be ``lambda = 1`` or ``lambda = 2``; every
other pole must be strictly decaying.  Cancelling the non-decaying tail is a
linear constraint problem, and once it is feasible the remaining energy is a
quadratic function of the free coefficients which is minimised exactly.
"""
from fractions import Fraction

from exchange.polynomials import (multiply_polynomials, reduce_rational,
                                  subtract_polynomials)
from review.difference import DifferenceResponse
from review.exact_linear import solve_linear_system, quadratic_form
from review.recurrence import realize_tail
from review.stability import is_strictly_schur

ZERO = (Fraction(0),)
ONE = (Fraction(1),)


def _trim(values):
    result = [Fraction(value) for value in values]
    while result and result[-1] == 0:
        result.pop()
    return tuple(result) or ZERO


def _shift(poly, count):
    return _trim((Fraction(0),) * count + tuple(poly))


def _poly_pow(base, exponent):
    result = ONE
    for _ in range(exponent):
        result = multiply_polynomials(result, base)
    return _trim(result)


def _divide(dividend, divisor):
    remainder = list(_trim(dividend))
    divisor = list(_trim(divisor))
    if divisor == [Fraction(0)]:
        raise ZeroDivisionError('cannot divide by the zero polynomial')
    quotient = [Fraction(0)] * max(0, len(remainder) - len(divisor) + 1)
    while remainder and len(remainder) >= len(divisor):
        offset = len(remainder) - len(divisor)
        factor = remainder[-1] / divisor[-1]
        quotient[offset] = factor
        for index, value in enumerate(divisor):
            remainder[index + offset] -= factor * value
        while remainder and remainder[-1] == 0:
            remainder.pop()
    return _trim(quotient), _trim(remainder)


def full_fraction(evidence):
    """Return the reduced numerator/denominator of direct + q*num/den."""
    denominator = tuple(evidence.denominator)
    direct = evidence.direct
    numerator = [Fraction(0)] * max(len(denominator), len(evidence.numerator) + 1)
    for index, value in enumerate(denominator):
        numerator[index] += direct * value
    for index, value in enumerate(evidence.numerator):
        numerator[index + 1] += value
    return reduce_rational(_trim(numerator), denominator)


def _strip_root(polynomial, root):
    """Divide by (1 - root*q) as often as possible, returning the multiplicity."""
    factor = (Fraction(1), -root)
    multiplicity = 0
    quotient, remainder = _divide(polynomial, factor)
    while remainder == ZERO:
        multiplicity += 1
        polynomial = quotient
        quotient, remainder = _divide(polynomial, factor)
    return polynomial, multiplicity


class PieceProfile:
    """A visible (reduced) piece split into allowed and decaying poles."""

    __slots__ = ('numerator', 'denominator', 'ones', 'twos')

    def __init__(self, numerator, denominator, ones, twos):
        self.numerator = numerator
        self.denominator = denominator
        self.ones = ones
        self.twos = twos


def profile_piece(evidence):
    """Reduce a piece and validate its non-decaying visible poles.

    Poles are the lambda of ``1 - lambda*q``; ``lambda = 1`` and
    ``lambda = 2`` may appear with any multiplicity, all remaining poles must
    be strictly decaying.  A single out-of-range pole rejects the request even
    if the two pieces would cancel it.
    """
    numerator, denominator = full_fraction(evidence)
    if denominator[0] != 1:
        raise ValueError('tail denominator must be normalized at q=0')
    remaining, ones = _strip_root(denominator, Fraction(1))
    remaining, twos = _strip_root(remaining, Fraction(2))
    if not is_strictly_schur(remaining):
        raise ValueError('a piece has a non-decaying pole other than 1 or 2')
    return PieceProfile(numerator, denominator, ones, twos)


def _series_quotient(numerator, denominator, count):
    numerator = list(_trim(numerator))
    denominator = list(_trim(denominator))
    if denominator[0] != 1:
        raise ValueError('series quotient requires a normalized denominator')
    series = []
    for index in range(count):
        value = numerator[index] if index < len(numerator) else Fraction(0)
        for lag in range(1, min(index, len(denominator) - 1) + 1):
            value -= denominator[lag] * series[index - lag]
        series.append(value)
    return series


def _tail_energy(tail):
    size = len(tail.initial)
    if size == 0:
        return Fraction(0)
    coordinates = [(i, j) for i in range(size) for j in range(i, size)]
    transition = tail.transition
    # P - A^T P A = C^T C over the symmetric entries of P.
    equations = []
    for i, j in coordinates:
        row = []
        for k, l in coordinates:
            propagated = transition[k][i] * transition[l][j]
            if k != l:
                propagated += transition[l][i] * transition[k][j]
            row.append(int((i, j) == (k, l)) - propagated)
        equations.append(row)
    constants = [tail.output[i] * tail.output[j] for i, j in coordinates]
    entries = solve_linear_system(equations, constants)
    gramian = [[Fraction(0)] * size for _ in range(size)]
    for (i, j), value in zip(coordinates, entries):
        gramian[i][j] = gramian[j][i] = value
    return quadratic_form(gramian, tail.initial)


class CompensationModel:
    """Precomputed decomposition shared by every candidate prescription."""

    def __init__(self, primary, reference):
        self.primary = profile_piece(primary)
        self.reference = profile_piece(reference)
        self.denominator = multiply_polynomials(self.primary.denominator,
                                                self.reference.denominator)
        self.ones = self.primary.ones + self.reference.ones
        self.twos = self.primary.twos + self.reference.twos
        self.nondecaying = multiply_polynomials(_poly_pow((Fraction(1), Fraction(-1)), self.ones),
                                                _poly_pow((Fraction(1), Fraction(-2)), self.twos))
        self.decaying, remainder = _divide(self.denominator, self.nondecaying)
        if remainder != ZERO:
            raise AssertionError('the non-decaying factors must divide the combined denominator')
        if not is_strictly_schur(self.decaying):
            raise AssertionError('the decaying factor must be a stable denominator')

    def _numerator(self, coefficients):
        """N = P_num*R_den - F*R_num*P_den, linear in the coefficients."""
        p, r = self.primary, self.reference
        return subtract_polynomials(
            multiply_polynomials(p.numerator, r.denominator),
            multiply_polynomials(coefficients,
                                 multiply_polynomials(r.numerator, p.denominator)),
        )

    def energy(self, coefficients):
        numerator = self._numerator(coefficients)
        quotient, remainder = _divide(numerator, self.nondecaying)
        if remainder != ZERO:
            return None
        polynomial, tail = _divide(quotient, self.decaying)
        total = sum(value * value for value in polynomial)
        if tail == ZERO:
            return total
        series = _series_quotient(tail, self.decaying, len(polynomial))
        cross = sum(coefficient * value for coefficient, value in zip(polynomial, series))
        realization = realize_tail(DifferenceResponse(Fraction(0), tail, self.decaying))
        return total + 2 * cross + _tail_energy(realization)

    def _root_constraints(self, base, slack, pole, multiplicity):
        if multiplicity == 0:
            return []
        factor = _poly_pow((Fraction(1), -pole), multiplicity)

        def padded(polynomial):
            _, remainder = _divide(polynomial, factor)
            values = list(remainder) + [Fraction(0)] * (multiplicity - len(remainder))
            return values[:multiplicity]

        base_remainder = padded(base)
        slack_remainders = [padded(term) for term in slack]
        rows = []
        for index in range(multiplicity):
            rows.append(([term[index] for term in slack_remainders], -base_remainder[index]))
        return rows


def _solve_affine(equations, variables):
    """Solve rows of (coefficients, rhs); return particular and nullspace basis."""
    matrix = [list(row) + [rhs] for row, rhs in equations]
    pivots = []
    rank = 0
    for column in range(variables):
        pivot = next((row for row in range(rank, len(matrix)) if matrix[row][column] != 0), None)
        if pivot is None:
            continue
        matrix[rank], matrix[pivot] = matrix[pivot], matrix[rank]
        divisor = matrix[rank][column]
        matrix[rank] = [value / divisor for value in matrix[rank]]
        for row in range(len(matrix)):
            if row != rank and matrix[row][column] != 0:
                factor = matrix[row][column]
                matrix[row] = [value - factor * entry
                               for value, entry in zip(matrix[row], matrix[rank])]
        pivots.append(column)
        rank += 1
        if rank == len(matrix):
            break
    for row in range(rank, len(matrix)):
        if all(matrix[row][column] == 0 for column in range(variables)) \
                and matrix[row][variables] != 0:
            return None
    particular = [Fraction(0)] * variables
    for index, column in enumerate(pivots):
        particular[column] = matrix[index][variables]
    free = [column for column in range(variables) if column not in pivots]
    nullspace = []
    for column in free:
        vector = [Fraction(0)] * variables
        vector[column] = Fraction(1)
        for index, pivot in enumerate(pivots):
            vector[pivot] = -matrix[index][column]
        nullspace.append(vector)
    return particular, nullspace


def _solve_consistent(matrix, constants):
    """Solve a possibly singular symmetric system, fixing free variables to zero."""
    solution = _solve_affine(list(zip(matrix, constants)), len(constants))
    if solution is None:
        raise AssertionError('the normal equations must be consistent')
    return solution[0]


def optimize(primary, reference, max_order, c0):
    """Return the exactly minimal ``(energy, coefficients)`` or ``None``.

    ``None`` means no choice of the trailing coefficients removes the
    non-decaying tail, so the residual energy is not finite.
    """
    model = CompensationModel(primary, reference)
    r = model.reference
    base = subtract_polynomials(
        multiply_polynomials(model.primary.numerator, r.denominator),
        multiply_polynomials((c0,), multiply_polynomials(r.numerator,
                                                         model.primary.denominator)),
    )
    slack = [tuple(-value for value in _shift(multiply_polynomials(
        r.numerator, model.primary.denominator), order))
        for order in range(1, max_order + 1)]
    equations = []
    equations += model._root_constraints(base, slack, Fraction(1), model.ones)
    equations += model._root_constraints(base, slack, Fraction(2), model.twos)
    solution = _solve_affine(equations, max_order)
    if solution is None:
        return None
    particular, nullspace = solution

    def coefficients(point):
        values = [c0] + list(particular)
        for weight, vector in zip(point, nullspace):
            for order in range(max_order):
                values[order + 1] += weight * vector[order]
        return tuple(values)

    dimension = len(nullspace)
    origin = [Fraction(0)] * dimension
    base_energy = model.energy(coefficients(origin))
    if dimension == 0:
        return base_energy, coefficients(origin)

    steps = []
    for index in range(dimension):
        forward = [Fraction(0)] * dimension
        backward = [Fraction(0)] * dimension
        forward[index] = Fraction(1)
        backward[index] = Fraction(-1)
        steps.append((model.energy(coefficients(forward)),
                      model.energy(coefficients(backward))))

    hessian = [[Fraction(0)] * dimension for _ in range(dimension)]
    gradient = [Fraction(0)] * dimension
    for index in range(dimension):
        plus, minus = steps[index]
        hessian[index][index] = (plus + minus - 2 * base_energy) / 2
        gradient[index] = (plus - minus) / 4
    for left in range(dimension):
        for right in range(left + 1, dimension):
            point = [Fraction(0)] * dimension
            point[left] = point[right] = Fraction(1)
            value = model.energy(coefficients(point))
            hessian[left][right] = hessian[right][left] = (
                value - steps[left][0] - steps[right][0] + base_energy) / 2

    point = _solve_consistent(hessian, [-value for value in gradient])
    best = coefficients(point)
    return model.energy(best), best
