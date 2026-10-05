"""Pure numpy measurements on a captured waveform. No plug, no driver, no I/O.

The functions accept anything shaped like a `Waveform` (see `WaveformLike`), so this module
does not import the plug. Every function refuses clipped data with `ClippedError` unless
called with ``allow_clipped=True``: a verdict computed from a clipped trace is wrong in a
way that looks plausible.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np
import numpy.typing as npt


class ClippedError(ValueError):
    """The waveform hit full scale (driver overflow flag or a sample at +/- max_adc)."""


class WaveformMetaLike(Protocol):
    """The part of `WaveformMeta` that measurements read."""

    @property
    def overflow(self) -> bool: ...

    @property
    def max_adc(self) -> int: ...

    @property
    def range_v(self) -> float: ...


class WaveformLike(Protocol):
    """Structural type of `Waveform`: volts, seconds, untouched ADC counts, metadata."""

    @property
    def v(self) -> npt.NDArray[np.float64]: ...

    @property
    def t(self) -> npt.NDArray[np.float64]: ...

    @property
    def raw(self) -> npt.NDArray[np.int16]: ...

    @property
    def meta(self) -> WaveformMetaLike: ...


def is_clipped(w: WaveformLike) -> bool:
    """True if the driver flagged overflow or any raw count is at +/- full scale (`max_adc`)."""
    if w.meta.overflow:
        return True
    if w.raw.size == 0:
        return False
    max_adc = w.meta.max_adc
    return int(w.raw.max()) >= max_adc or int(w.raw.min()) <= -max_adc


def _check(w: WaveformLike, allow_clipped: bool) -> npt.NDArray[np.float64]:
    if not allow_clipped and is_clipped(w):
        raise ClippedError(
            "waveform is clipped (overflow flag or a sample at full scale); "
            "use a larger range or pass allow_clipped=True"
        )
    if w.v.size == 0:
        raise ValueError("empty waveform")
    return w.v


def vmax(w: WaveformLike, *, allow_clipped: bool = False) -> float:
    """Maximum voltage."""
    return float(_check(w, allow_clipped).max())


def vmin(w: WaveformLike, *, allow_clipped: bool = False) -> float:
    """Minimum voltage."""
    return float(_check(w, allow_clipped).min())


def vpp(w: WaveformLike, *, allow_clipped: bool = False) -> float:
    """Peak-to-peak voltage, `max(v) - min(v)`."""
    v = _check(w, allow_clipped)
    return float(v.max() - v.min())


def vmean(w: WaveformLike, *, allow_clipped: bool = False) -> float:
    """Mean voltage."""
    return float(_check(w, allow_clipped).mean())


def vrms(w: WaveformLike, *, allow_clipped: bool = False) -> float:
    """RMS of `v` as is (not AC-coupled: a DC offset counts)."""
    v = _check(w, allow_clipped)
    return float(np.sqrt(np.mean(v * v)))


def frequency_hz(
    w: WaveformLike,
    *,
    low: float = 0.3,
    high: float = 0.7,
    min_vpp: float | None = None,
    allow_clipped: bool = False,
) -> float:
    """Frequency of a periodic signal from rising crossings, with hysteresis.

    Algorithm (as in rigol-dho-openhtf):

    1. ``lo`` and ``hi`` are the 5th and 95th percentile of ``v``; they ignore outliers
       such as single-sample glitches.
    2. A rising crossing is a transition from "below ``lo + low*(hi-lo)``" to "above
       ``lo + high*(hi-lo)``". Samples between the two thresholds change nothing, so noise
       around one level cannot produce extra crossings. Defaults: ``low=0.3``, ``high=0.7``;
       they must satisfy ``0 <= low < high <= 1``.
    3. The time of a crossing is the linear interpolation of the ``high`` threshold between
       the last sample before it and the first sample at or above it (the same offset for
       every crossing, so it cancels in the difference).
    4. ``frequency = (n_crossings - 1) / (t_last_crossing - t_first_crossing)``.

    Fewer than two crossings (DC, a single edge, a flat trace) raise
    ``ValueError("not periodic")``. So does an amplitude ``hi - lo`` below ``min_vpp`` volts
    (default: 4 ADC codes, ``4 * range_v / max_adc``): without it the percentile levels of a flat
    trace with a code or two of ADC noise (a disconnected probe) would produce hundreds of
    "crossings" and a plausible-looking frequency.
    """
    if not 0.0 <= low < high <= 1.0:
        raise ValueError(f"need 0 <= low < high <= 1, got low={low}, high={high}")
    v = _check(w, allow_clipped)
    lo, hi = np.percentile(v, [5.0, 95.0])
    if min_vpp is None:
        min_vpp = 4 * w.meta.range_v / w.meta.max_adc  # 4 ADC codes
    if hi - lo < min_vpp:
        raise ValueError("not periodic")
    low_level = lo + low * (hi - lo)
    high_level = lo + high * (hi - lo)
    below = v < low_level
    above = v >= high_level
    decided = np.flatnonzero(below | above)  # samples that are clearly low or clearly high
    is_high = above[decided]
    rising = np.flatnonzero(~is_high[:-1] & is_high[1:])
    if rising.size < 2:
        raise ValueError("not periodic")
    idx = decided[rising + 1]  # first sample at or above `high_level` after a low one
    t = w.t
    v0, v1 = v[idx - 1], v[idx]
    frac = (high_level - v0) / (v1 - v0)
    t_cross = t[idx - 1] + frac * (t[idx] - t[idx - 1])
    span = float(t_cross[-1] - t_cross[0])
    if span <= 0.0:
        raise ValueError("not periodic")
    return float((t_cross.size - 1) / span)


def period_s(
    w: WaveformLike,
    *,
    low: float = 0.3,
    high: float = 0.7,
    min_vpp: float | None = None,
    allow_clipped: bool = False,
) -> float:
    """Period in seconds, the inverse of `frequency_hz`."""
    return 1.0 / frequency_hz(w, low=low, high=high, min_vpp=min_vpp, allow_clipped=allow_clipped)
