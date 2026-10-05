import pytest

from picoscope_2000_openhtf import units
from picoscope_2000_openhtf.units import V, ms, mV, ns, s, us


def test_values() -> None:
    assert V == 1.0
    assert mV == 1e-3
    assert s == 1.0
    assert ms == 1e-3
    assert us == 1e-6
    assert ns == 1e-9


def test_usage() -> None:
    assert 2 * V == 2.0
    assert 500 * mV == 0.5
    assert 1 * us == 1e-6
    assert 1000 * ns == pytest.approx(1 * us)


def test_all_floats_and_nothing_else_public() -> None:
    names = {n for n in vars(units) if not n.startswith("_")}
    assert names == {"V", "mV", "s", "ms", "us", "ns"}
    assert all(isinstance(getattr(units, n), float) for n in names)
