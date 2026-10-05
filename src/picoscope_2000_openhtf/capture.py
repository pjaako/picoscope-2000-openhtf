"""Capture conditions for a single-shot block capture, as frozen validated dataclasses.

A `Capture` is plain data: it names the enabled channels with their voltage ranges, the
requested sample interval, the pre/post-trigger sample counts and an optional edge trigger.
Nothing here talks to the driver; the plug turns a `Capture` into driver calls.

The tables below map the user-facing numbers and strings to the manual's enum member names
(ps2000a programmer's guide, ps2000apg.en-12, "PG").
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from .units import V, mV

RANGES: Mapping[float, str] = {  # PG §3.39, full-scale volts -> enum name
    20 * mV: "PS2000A_20MV",  # PG §3.39
    50 * mV: "PS2000A_50MV",  # PG §3.39
    100 * mV: "PS2000A_100MV",  # PG §3.39
    200 * mV: "PS2000A_200MV",  # PG §3.39
    500 * mV: "PS2000A_500MV",  # PG §3.39
    1 * V: "PS2000A_1V",  # PG §3.39
    2 * V: "PS2000A_2V",  # PG §3.39
    5 * V: "PS2000A_5V",  # PG §3.39
    10 * V: "PS2000A_10V",  # PG §3.39
    20 * V: "PS2000A_20V",  # PG §3.39
}
CHANNEL_NAMES: Mapping[int, str] = {
    1: "PS2000A_CHANNEL_A",  # PG §3.39
    2: "PS2000A_CHANNEL_B",  # PG §3.39
    3: "PS2000A_CHANNEL_C",  # PG §3.39
    4: "PS2000A_CHANNEL_D",  # PG §3.39
}
COUPLINGS: Mapping[str, str] = {
    "AC": "PS2000A_AC",  # PG §3.39
    "DC": "PS2000A_DC",  # PG §3.39
}
# PG §3.56 lists ABOVE, BELOW, RISING, FALLING and RISING_OR_FALLING for the simple trigger;
# the full member names are in the PS2000A_THRESHOLD_DIRECTION table of PG §3.58.
DIRECTIONS: Mapping[str, str] = {
    "ABOVE": "PS2000A_ABOVE",  # PG §3.56
    "BELOW": "PS2000A_BELOW",  # PG §3.56
    "RISING": "PS2000A_RISING",  # PG §3.56
    "FALLING": "PS2000A_FALLING",  # PG §3.56
    "RISING_OR_FALLING": "PS2000A_RISING_OR_FALLING",  # PG §3.56
}

MAX_AUTO_MS = 32767  # PG §3.56: autoTrigger_ms is an int16_t
_REL_TOL = 1e-9


def _is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _is_int(x: object) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _raise_if(problems: list[str], what: str) -> None:
    if problems:
        raise ValueError(f"invalid {what}: " + "; ".join(problems))


def _range_key(value: object) -> float | None:
    """Return the `RANGES` key equal to `value` (relative tolerance 1e-9), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    for key in RANGES:
        if math.isclose(float(value), key, rel_tol=_REL_TOL):
            return key
    return None


@dataclass(frozen=True, kw_only=True)
class Channel:
    """One enabled analog input: number 1..4 (A..D), full-scale range in volts, coupling."""

    ch: int
    range: float
    coupling: Literal["AC", "DC"] = "DC"

    def __post_init__(self) -> None:
        problems: list[str] = []
        if not _is_int(self.ch) or self.ch not in CHANNEL_NAMES:
            problems.append(f"ch must be an integer in 1..4, got {self.ch!r}")
        key = _range_key(self.range)
        if key is None:
            valid = ", ".join(f"{k:g}" for k in RANGES)
            problems.append(f"range must be one of {valid} V, got {self.range!r}")
        else:
            object.__setattr__(self, "range", key)
        if self.coupling not in COUPLINGS:
            problems.append(f"coupling must be one of {sorted(COUPLINGS)}, got {self.coupling!r}")
        _raise_if(problems, "Channel")


@dataclass(frozen=True, kw_only=True)
class Edge:
    """Edge trigger on one channel. `level` is in volts.

    `delay_samples` (sample periods, PG §3.56) must be 0 in phase 1: a delay moves the trigger
    instant off index `pre_samples` (open question 30) and the time axis does not model that.
    """

    source: int
    level: float
    direction: Literal["ABOVE", "BELOW", "RISING", "FALLING", "RISING_OR_FALLING"] = "RISING"
    auto_ms: int = 0
    delay_samples: int = 0

    def __post_init__(self) -> None:
        problems: list[str] = []
        if not _is_int(self.source) or self.source not in CHANNEL_NAMES:
            problems.append(f"source must be an integer in 1..4, got {self.source!r}")
        if not _is_number(self.level) or not math.isfinite(self.level):
            problems.append(f"level must be a finite number of volts, got {self.level!r}")
        if self.direction not in DIRECTIONS:
            problems.append(
                f"direction must be one of {sorted(DIRECTIONS)}, got {self.direction!r}"
            )
        if not _is_int(self.auto_ms) or not 0 <= self.auto_ms <= MAX_AUTO_MS:
            problems.append(f"auto_ms must be an integer in 0..{MAX_AUTO_MS}, got {self.auto_ms!r}")
        if not _is_int(self.delay_samples) or self.delay_samples != 0:
            # PG §3.56 `delay` moves the trigger instant away from sample index pre_samples,
            # which the time axis of a Waveform does not model (open question 30).
            problems.append(
                f"delay_samples must be 0 in phase 1 (a delay moves the trigger instant, "
                f"open question 30), got {self.delay_samples!r}"
            )
        _raise_if(problems, "Edge")


@dataclass(frozen=True, kw_only=True)
class Capture:
    """Everything needed to arm one block capture.

    `sample_interval` is the *requested* interval in seconds; the driver picks the nearest
    timebase at or above it and the plug records the real one. `pre_samples` and
    `post_samples` are counted around the trigger point.
    """

    channels: tuple[Channel, ...]
    sample_interval: float
    pre_samples: int
    post_samples: int
    trigger: Edge | None = None

    def __post_init__(self) -> None:
        problems: list[str] = []
        channels = self.channels
        if isinstance(channels, list):  # tolerate a list, store a tuple
            channels = tuple(channels)
            object.__setattr__(self, "channels", channels)
        if not isinstance(channels, tuple) or not all(isinstance(c, Channel) for c in channels):
            problems.append("channels must be a tuple of Channel")
            channels = ()
        elif not 1 <= len(channels) <= 4:
            problems.append(f"channels must hold 1..4 entries, got {len(channels)}")
        numbers = [c.ch for c in channels]
        duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
        if duplicates:
            problems.append(f"channel numbers must be distinct, repeated: {duplicates}")
        if (
            not _is_number(self.sample_interval)
            or not math.isfinite(self.sample_interval)
            or self.sample_interval <= 0
        ):
            problems.append(
                f"sample_interval must be a finite number > 0, got {self.sample_interval!r}"
            )
        pre_ok = _is_int(self.pre_samples) and self.pre_samples >= 0
        post_ok = _is_int(self.post_samples) and self.post_samples >= 0
        if not pre_ok:
            problems.append(f"pre_samples must be an integer >= 0, got {self.pre_samples!r}")
        if not post_ok:
            problems.append(f"post_samples must be an integer >= 0, got {self.post_samples!r}")
        if pre_ok and post_ok and self.pre_samples + self.post_samples <= 0:
            problems.append("pre_samples + post_samples must be > 0")
        if self.trigger is not None:
            if not isinstance(self.trigger, Edge):
                problems.append(f"trigger must be an Edge or None, got {self.trigger!r}")
            else:
                source = next((c for c in channels if c.ch == self.trigger.source), None)
                if source is None:
                    if channels:
                        problems.append(
                            f"trigger source {self.trigger.source} is not one of the "
                            f"channels {sorted(numbers)}"
                        )
                elif abs(self.trigger.level) > source.range and not math.isclose(
                    abs(self.trigger.level), source.range, rel_tol=_REL_TOL
                ):
                    problems.append(
                        f"trigger level {self.trigger.level:g} V exceeds the range "
                        f"{source.range:g} V of channel {source.ch}"
                    )
        _raise_if(problems, "Capture")

    @property
    def total_samples(self) -> int:
        """`pre_samples + post_samples`."""
        return self.pre_samples + self.post_samples

    def channel(self, ch: int) -> Channel:
        """The `Channel` with number `ch`; `ValueError` if it is not enabled."""
        for c in self.channels:
            if c.ch == ch:
                return c
        raise ValueError(f"channel {ch} is not enabled in this capture")

    def enabled(self) -> tuple[int, ...]:
        """Enabled channel numbers in ascending order."""
        return tuple(sorted(c.ch for c in self.channels))

    def trigger_threshold_adc(self, max_adc: int) -> int:
        """Trigger level as an ADC count: `round(level / range * max_adc)` (PG §3.56, §2.3)."""
        if self.trigger is None:
            raise ValueError("capture has no trigger")
        source = self.channel(self.trigger.source)
        return round(self.trigger.level / source.range * max_adc)
