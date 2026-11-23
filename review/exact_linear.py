from fractions import Fraction


def solve_linear_system(matrix, constants) -> tuple[Fraction, ...]:
    """Solve a nonsingular square system by exact Gauss–Jordan elimination."""
    size = len(constants)
    if len(matrix) != size or any(len(row) != size for row in matrix):
        raise ValueError('a square linear system is required')
    work = [[*map(Fraction, row), Fraction(value)] for row, value in zip(matrix, constants)]
    for column in range(size):
        pivot = next((i for i in range(column, size) if work[i][column]), None)
        if pivot is None:
            raise ValueError('singular linear system')
        work[column], work[pivot] = work[pivot], work[column]
        divisor = work[column][column]
        pivot_row = [value / divisor for value in work[column]]
        work[column] = pivot_row
        for i, row in enumerate(work):
            if i != column and row[column]:
                factor = row[column]
                work[i] = [value - factor * entry for value, entry in zip(row, pivot_row)]
    return tuple(row[-1] for row in work)


def quadratic_form(matrix, vector) -> Fraction:
    size = len(vector)
    if len(matrix) != size or any(len(row) != size for row in matrix):
        raise ValueError('quadratic form dimension mismatch')
    return sum((left * coefficient * right
                for left, row in zip(vector, matrix)
                for coefficient, right in zip(row, vector)), Fraction(0))
