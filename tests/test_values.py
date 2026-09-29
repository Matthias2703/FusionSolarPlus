"""Tests for the portal-value parsing helpers.

These import only api/values.py, which has no Home Assistant or requests
dependency, so they run with a plain `pip install pytest`.
"""

import importlib.util
import pathlib

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "custom_components"
    / "fusionsolarplus"
    / "api"
    / "values.py"
)


def load_values():
    spec = importlib.util.spec_from_file_location("fusionsolarplus_values", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


values = load_values()


def test_finite_or_none_keeps_real_numbers():
    assert values.finite_or_none(1.5) == 1.5
    assert values.finite_or_none(-2.0) == -2.0
    assert values.finite_or_none(0.0) == 0.0


def test_finite_or_none_rejects_nan_and_inf():
    assert values.finite_or_none(float("nan")) is None
    assert values.finite_or_none(float("inf")) is None
    assert values.finite_or_none(float("-inf")) is None


def test_numeric_or_zero_keeps_negative_readings():
    # This is the actual bug: a battery discharging at 1.5 kW is reported as
    # "-1.5", and a naive `"-" in value` check used to zero it out.
    assert values.numeric_or_zero("-1.5") == -1.5
    assert values.numeric_or_zero("-0.1") == -0.1


def test_numeric_or_zero_keeps_positive_readings():
    assert values.numeric_or_zero("3.7") == 3.7
    assert values.numeric_or_zero("0") == 0.0


def test_numeric_or_zero_turns_placeholders_into_zero():
    assert values.numeric_or_zero("-") == 0.0
    assert values.numeric_or_zero("") == 0.0
    assert values.numeric_or_zero(None) == 0.0


def test_numeric_or_zero_rejects_nan_and_inf():
    assert values.numeric_or_zero("nan") == 0.0
    assert values.numeric_or_zero("inf") == 0.0
