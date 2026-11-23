from dataclasses import dataclass
from fractions import Fraction

from review.difference import DifferenceResponse
from review.exact_linear import quadratic_form, solve_linear_system
from review.recurrence import TailRealization, realize_tail
from review.stability import is_strictly_schur


@dataclass(frozen=True)
class EnergyResult:
    energy: Fraction | None

    @property
    def status(self) -> str:
        return 'divergent' if self.energy is None else 'finite'


def _tail_energy(tail: TailRealization) -> Fraction:
    size = len(tail.initial)
    coordinates = [(i, j) for i in range(size) for j in range(i, size)]
    a = tail.transition
    # Solve P - Aᵀ P A = Cᵀ C using only the symmetric entries of P.
    equations = []
    for i, j in coordinates:
        row = []
        for k, l in coordinates:
            propagated = a[k][i] * a[l][j]
            if k != l:
                propagated += a[l][i] * a[k][j]
            row.append(int((i, j) == (k, l)) - propagated)
        equations.append(row)
    constants = [tail.output[i] * tail.output[j] for i, j in coordinates]
    entries = solve_linear_system(equations, constants)
    gramian = [[Fraction(0)] * size for _ in range(size)]
    for (i, j), value in zip(coordinates, entries):
        gramian[i][j] = gramian[j][i] = value
    return quadratic_form(gramian, tail.initial)


def compute_energy(response: DifferenceResponse) -> EnergyResult:
    # A reduced q denominator gives the characteristic coefficients in reverse power order.
    # Additional states for finite polynomial terms contribute only zero poles.
    if not is_strictly_schur(response.denominator):
        return EnergyResult(None)
    tail = realize_tail(response)
    return EnergyResult(response.direct ** 2 + _tail_energy(tail))
