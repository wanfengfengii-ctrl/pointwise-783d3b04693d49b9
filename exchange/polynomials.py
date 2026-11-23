import re
from fractions import Fraction


_RATIONAL = re.compile(r'[+-]?[0-9]+(?:/[0-9]+)?')
_ZERO = (Fraction(0),)
_ONE = (Fraction(1),)


def parse_rational(value) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if type(value) is int:
        return Fraction(value)
    if isinstance(value, str) and _RATIONAL.fullmatch(value):
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError) as error:
            raise ValueError('invalid rational coefficient') from error
    raise ValueError('expected an exact rational number')


def _trim(values):
    values = list(values)
    while values and values[-1] == 0:
        values.pop()
    return tuple(values) or _ZERO


def multiply_polynomials(left, right):
    left, right = _trim(left), _trim(right)
    result = [Fraction(0)] * (len(left) + len(right) - 1)
    for i, a in enumerate(left):
        for j, b in enumerate(right):
            result[i + j] += a * b
    return _trim(result)


def subtract_polynomials(left, right):
    left, right = tuple(left), tuple(right)
    result = [Fraction(0)] * max(len(left), len(right))
    for i, value in enumerate(left):
        result[i] += value
    for i, value in enumerate(right):
        result[i] -= value
    return _trim(result)


def _divide(dividend, divisor):
    remainder = list(_trim(dividend))
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


def reduce_rational(numerator, denominator):
    """Cancel the polynomial gcd and normalize the denominator at q=0."""
    numerator = _trim(map(parse_rational, numerator))
    denominator = _trim(map(parse_rational, denominator))
    if not denominator[0]:
        raise ValueError('tail denominator must be nonzero at q=0')
    if numerator == _ZERO:
        return _ZERO, _ONE
    left, right = denominator, numerator
    while right != _ZERO:
        _, remainder = _divide(left, right)
        left, right = right, remainder
    numerator, _ = _divide(numerator, left)
    denominator, _ = _divide(denominator, left)
    scale = denominator[0]
    return tuple(value / scale for value in numerator), tuple(value / scale for value in denominator)
