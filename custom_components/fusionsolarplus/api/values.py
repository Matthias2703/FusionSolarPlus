"""Helpers for turning portal signal values into numbers."""

import math


def finite_or_none(number: float) -> float | None:
    """float("NaN") and float("inf") parse fine but are not usable sensor values."""
    return number if math.isfinite(number) else None
