from fractions import Fraction


def is_strictly_schur(coefficients) -> bool:
    """Test real polynomial coefficients in descending powers of the pole variable."""
    coefficients = tuple(map(Fraction, coefficients))
    if not coefficients or not coefficients[0]:
        raise ValueError('a nonzero leading polynomial coefficient is required')
    while len(coefficients) > 1:
        leading, last = coefficients[0], coefficients[-1]
        if abs(last) >= abs(leading):
            return False
        # Remove the zero constant term of leading * p - last * reversed(p).
        coefficients = tuple(leading * current - last * reverse
                             for current, reverse in zip(coefficients[:-1], reversed(coefficients)))
    return True
