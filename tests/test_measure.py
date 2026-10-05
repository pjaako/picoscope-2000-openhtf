from typing import NamedTuple

import numpy as np
import numpy.typing as npt
import pytest

from picoscope_2000_openhtf.measure import (
    ClippedError,
    WaveformLike,
    frequency_hz,
    is_clipped,
    period_s,
    vmax,
    vmean,
    vmin,
    vpp,
    vrms,
)

MAX_ADC = 32512


class Meta(NamedTuple):
    overflow: bool
    max_adc: int


class Wave(NamedTuple):
    t: npt.NDArray[np.float64]
    v: npt.NDArray[np.float64]
    raw: npt.NDArray[np.int16]
    meta: Meta


def make(
    v: npt.NDArray[np.float64], dt: float, *, range_v: float = 2.0, overflow: bool = False
) -> WaveformLike:
    """Waveform from volts: quantise to counts like the driver would, recompute v."""
    raw = np.clip(np.round(v / range_v * MAX_ADC), -MAX_ADC, MAX_ADC).astype(np.int16)
    vq = raw.astype(np.float64) * (range_v / MAX_ADC)
    t = np.arange(len(raw), dtype=np.float64) * dt
    return Wave(t=t, v=vq, raw=raw, meta=Meta(overflow=overflow, max_adc=MAX_ADC))


def sine(
    freq: float, dt: float, n: int, amp: float = 1.0, offset: float = 0.0, phase: float = 0.3
) -> npt.NDArray[np.float64]:
    t = np.arange(n) * dt
    return offset + amp * np.sin(2 * np.pi * freq * t + phase)


def square(freq: float, dt: float, n: int, high: float = 1.0) -> npt.NDArray[np.float64]:
    t = np.arange(n) * dt
    return np.where((t * freq) % 1.0 < 0.5, high, 0.0).astype(np.float64)


# --- amplitudes -----------------------------------------------------------------------------


def test_vpp_vmin_vmax_vmean() -> None:
    w = make(sine(1000.0, 1e-6, 20000, amp=1.5, offset=0.25), 1e-6, range_v=5.0)
    assert vmax(w) == pytest.approx(1.75, abs=1e-3)
    assert vmin(w) == pytest.approx(-1.25, abs=1e-3)
    assert vpp(w) == pytest.approx(3.0, abs=2e-3)
    assert vmean(w) == pytest.approx(0.25, abs=1e-3)


def test_vrms_of_sine_is_amplitude_over_root_two() -> None:
    w = make(sine(1000.0, 1e-6, 10000, amp=1.0, phase=0.0), 1e-6)  # exactly 10 periods
    assert vrms(w) == pytest.approx(1.0 / np.sqrt(2.0), rel=1e-3)


def test_vrms_is_not_ac_coupled() -> None:
    w = make(np.full(100, 0.5), 1e-6)
    assert vrms(w) == pytest.approx(0.5, abs=1e-3)


def test_vrms_of_square() -> None:
    w = make(square(1000.0, 1e-6, 10000, high=1.0), 1e-6)  # 0/1 square: rms = sqrt(0.5)
    assert vrms(w) == pytest.approx(np.sqrt(0.5), rel=1e-3)


def test_return_types_are_python_floats() -> None:
    w = make(sine(1000.0, 1e-6, 5000), 1e-6)
    for f in (vpp, vmean, vrms, vmin, vmax, frequency_hz, period_s):
        assert type(f(w)) is float


def test_empty_waveform() -> None:
    w = make(np.zeros(0), 1e-6)
    with pytest.raises(ValueError, match="empty"):
        vpp(w)
    assert is_clipped(w) is False


# --- frequency ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("freq", "dt", "n"),
    [
        (1000.0, 1e-6, 3000),  # 3 periods, 1000 samples per period
        (1000.0, 1e-6, 20000),  # 20 periods, 1000 samples per period
        (997.0, 1e-6, 15000),  # period not a whole number of samples
        (50.0, 100e-6, 5000),  # 10 periods at 200 samples per period
        (123456.0, 20e-9, 10000),  # about 24.7 periods, 405 samples per period
        (1e6, 50e-9, 2000),  # 20 samples per period
    ],
)
def test_frequency_of_sine(freq: float, dt: float, n: int) -> None:
    w = make(sine(freq, dt, n), dt)
    assert frequency_hz(w) == pytest.approx(freq, rel=1e-3)


@pytest.mark.parametrize("freq", [1000.0, 1001.7, 4321.0])
def test_frequency_of_square_at_least_ten_periods(freq: float) -> None:
    dt = 1e-6
    n = int(12.5 / freq / dt)
    w = make(square(freq, dt, n, high=1.0), dt)
    assert frequency_hz(w) == pytest.approx(freq, rel=1e-3)


def test_frequency_with_dc_offset_and_other_range() -> None:
    w = make(sine(2500.0, 2e-6, 8000, amp=0.3, offset=0.4), 2e-6, range_v=1.0)
    assert frequency_hz(w) == pytest.approx(2500.0, rel=1e-3)


def test_frequency_hysteresis_ignores_dip_between_thresholds() -> None:
    v = square(1000.0, 1e-6, 12000, high=1.0)
    v[3333] = 0.5  # dip inside a high phase, between the 0.3 and 0.7 levels: no new crossing
    w = make(v, 1e-6)
    assert frequency_hz(w) == pytest.approx(1000.0, rel=1e-3)


def test_frequency_with_noise_does_not_double_count() -> None:
    rng = np.random.default_rng(1234)
    v = sine(1000.0, 1e-6, 20000) + rng.normal(0.0, 0.05, 20000)
    w = make(v, 1e-6)
    assert frequency_hz(w) == pytest.approx(1000.0, rel=1e-3)


def test_frequency_custom_thresholds() -> None:
    w = make(sine(1000.0, 1e-6, 10000), 1e-6)
    assert frequency_hz(w, low=0.4, high=0.6) == pytest.approx(1000.0, rel=1e-3)


@pytest.mark.parametrize("low_high", [(0.7, 0.3), (0.5, 0.5), (-0.1, 0.5), (0.2, 1.5)])
def test_frequency_rejects_bad_thresholds(low_high: tuple[float, float]) -> None:
    w = make(sine(1000.0, 1e-6, 5000), 1e-6)
    with pytest.raises(ValueError, match="low < high"):
        frequency_hz(w, low=low_high[0], high=low_high[1])


def test_frequency_not_periodic_dc() -> None:
    with pytest.raises(ValueError, match="not periodic"):
        frequency_hz(make(np.full(1000, 0.2), 1e-6))


def test_frequency_not_periodic_single_edge() -> None:
    v = np.concatenate([np.zeros(500), np.ones(500)])
    with pytest.raises(ValueError, match="not periodic"):
        frequency_hz(make(v, 1e-6))


def test_frequency_not_periodic_ramp() -> None:
    with pytest.raises(ValueError, match="not periodic"):
        frequency_hz(make(np.linspace(-1.0, 1.0, 2000), 1e-6))


def test_frequency_two_crossings_is_enough() -> None:
    v = square(1000.0, 1e-6, 2500, high=1.0)  # rising edges at 0 is high; 1 ms, 2 ms
    w = make(v, 1e-6)
    assert frequency_hz(w) == pytest.approx(1000.0, rel=1e-3)


def test_period_is_inverse_of_frequency() -> None:
    w = make(sine(1000.0, 1e-6, 10000), 1e-6)
    assert period_s(w) == pytest.approx(1e-3, rel=1e-3)
    assert period_s(w) == pytest.approx(1.0 / frequency_hz(w), rel=1e-12)
    with pytest.raises(ValueError, match="not periodic"):
        period_s(make(np.zeros(100), 1e-6))


# --- clipping -------------------------------------------------------------------------------


def _clipped_waves() -> dict[str, WaveformLike]:
    v = sine(1000.0, 1e-6, 10000)
    clipped_pos = v.copy()
    clipped_pos[5] = 9.0  # beyond range 2 V -> clipped to +max_adc by make()
    clipped_neg = v.copy()
    clipped_neg[7] = -9.0
    return {
        "overflow": make(v, 1e-6, overflow=True),
        "positive": make(clipped_pos, 1e-6),
        "negative": make(clipped_neg, 1e-6),
    }


@pytest.mark.parametrize("kind", ["overflow", "positive", "negative"])
def test_is_clipped_true(kind: str) -> None:
    assert is_clipped(_clipped_waves()[kind]) is True


def test_is_clipped_false_just_below_full_scale() -> None:
    raw = np.array([0, MAX_ADC - 1, -(MAX_ADC - 1)], dtype=np.int16)
    w = Wave(
        t=np.arange(3, dtype=np.float64),
        v=raw.astype(np.float64),
        raw=raw,
        meta=Meta(overflow=False, max_adc=MAX_ADC),
    )
    assert is_clipped(w) is False


def test_is_clipped_at_exactly_full_scale() -> None:
    for value in (MAX_ADC, -MAX_ADC):
        raw = np.array([0, value, 0], dtype=np.int16)
        w = Wave(
            t=np.arange(3, dtype=np.float64),
            v=raw.astype(np.float64),
            raw=raw,
            meta=Meta(overflow=False, max_adc=MAX_ADC),
        )
        assert is_clipped(w) is True


@pytest.mark.parametrize("kind", ["overflow", "positive", "negative"])
@pytest.mark.parametrize("fn", [vpp, vmean, vrms, vmin, vmax, frequency_hz, period_s])
def test_every_function_raises_clipped_error(kind: str, fn: object) -> None:
    w = _clipped_waves()[kind]
    with pytest.raises(ClippedError):
        fn(w)  # type: ignore[operator]


@pytest.mark.parametrize("fn", [vpp, vmean, vrms, vmin, vmax, frequency_hz, period_s])
def test_allow_clipped_lets_everything_through(fn: object) -> None:
    w = _clipped_waves()["overflow"]
    assert isinstance(fn(w, allow_clipped=True), float)  # type: ignore[operator]


def test_clipped_error_is_a_value_error() -> None:
    assert issubclass(ClippedError, ValueError)
    w = _clipped_waves()["overflow"]
    with pytest.raises(ValueError, match="clipped"):
        vpp(w)


def test_unclipped_waveform_passes() -> None:
    w = make(sine(1000.0, 1e-6, 10000, amp=1.0), 1e-6, range_v=2.0)
    assert is_clipped(w) is False
    assert vpp(w) == pytest.approx(2.0, abs=2e-3)
