"""Helpers for turning portal signal values into numbers.

The FusionSolar portal represents "no value" in more than one way (an empty
placeholder string, or a numeric field that happens to parse as NaN/inf), and
none of them should ever reach a Home Assistant sensor as a real number.
"""

from __future__ import annotations

import math


def finite_or_none(number: float) -> float | None:
    """float("nan") and float("inf") parse fine but are not usable sensor values."""
    return number if math.isfinite(number) else None


def numeric_or_zero(value) -> float:
    """Portal placeholders such as "-" mean "no value"; real negatives must survive.

    A naive `"-" in value` check (used for this in earlier code) also matches a
    genuine negative reading such as "-1.5" - e.g. a battery that is discharging -
    and incorrectly zeroes it out. Parsing the value instead tells the two apart.
    """
    try:
        return finite_or_none(float(value)) or 0.0
    except (TypeError, ValueError):
        return 0.0
