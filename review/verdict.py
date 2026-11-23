from enum import StrEnum
from fractions import Fraction

from review.energy import EnergyResult


class Verdict(StrEnum):
    RELEASE = 'release'
    RETEST = 'retest'


def decide_verdict(result: EnergyResult, threshold: Fraction) -> Verdict:
    if result.energy is not None and result.energy <= threshold:
        return Verdict.RELEASE
    return Verdict.RETEST
