from dataclasses import dataclass
from fractions import Fraction

from review.difference import DifferenceResponse


@dataclass(frozen=True)
class TailRealization:
    initial: tuple[Fraction, ...]
    transition: tuple[tuple[Fraction, ...], ...]
    output: tuple[Fraction, ...]


def realize_tail(response: DifferenceResponse) -> TailRealization:
    numerator, denominator = response.numerator, response.denominator
    if numerator == (0,):
        return TailRealization((), (), ())
    degree = len(denominator) - 1
    size = max(degree, len(numerator))
    initial = []
    for index in range(size):
        feed = numerator[index] if index < len(numerator) else Fraction(0)
        previous = sum(denominator[lag] * initial[index - lag]
                       for lag in range(1, min(degree, index) + 1))
        initial.append(feed - previous)
    # Keep enough initial coefficients for an improper or polynomial tail.
    shifts = tuple(tuple(Fraction(j == i + 1) for j in range(size)) for i in range(size - 1))
    recurrence = (*denominator[1:], *((Fraction(0),) * (size - degree)))
    last = tuple(-value for value in reversed(recurrence))
    output = (Fraction(1),) + (Fraction(0),) * (size - 1)
    return TailRealization(tuple(initial), (*shifts, last), output)
