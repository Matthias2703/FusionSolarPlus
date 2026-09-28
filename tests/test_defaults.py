"""Guard rails for defaults that protect users' hardware."""

import importlib.util
import pathlib

CONST = (
    pathlib.Path(__file__).resolve().parents[1]
    / "custom_components"
    / "fusionsolarplus"
    / "const.py"
)


def load_const():
    spec = importlib.util.spec_from_file_location("fusionsolarplus_const", CONST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_charger_control_is_off_by_default():
    # Nobody gets write access to their wallbox without opting in.
    assert load_const().DEFAULT_CHARGER_CONTROL is False


def test_scan_interval_bounds_are_sane():
    const = load_const()
    assert const.MIN_SCAN_INTERVAL <= const.DEFAULT_SCAN_INTERVAL <= const.MAX_SCAN_INTERVAL
