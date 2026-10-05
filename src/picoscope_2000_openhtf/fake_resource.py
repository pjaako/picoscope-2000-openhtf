"""In-memory stand-in for the ps2000a driver, used by every hardware-free test.

`FakePs2000a` implements the `Ps2000aApi` seam of `driver.py` (SPEC section 3.1): one method
per manual function, named like the C function, enum arguments as the manual's member names,
status first in the returned tuple. It imports only numpy and the standard library; in
particular it must not import this package, `picosdk` or `openhtf`.

A fake only knows what we told it. Everything the manual leaves open is marked
`# ASSUMPTION(hw): ...` and listed in `docs/api_reference.md` "Open questions for hardware
verification"; hardware acceptance corrects this file to match the real unit. Citations
`PG §x.y` are sections of the ps2000a programmer's guide (ps2000apg.en-12), transcribed in
`docs/api_reference.md`.
"""

import math
import weakref
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import numpy.typing as npt

__all__ = ["STATUS", "ChannelConfig", "FakePs2000a", "FakeUnit", "TriggerConfig"]

# Status codes. Values copied from picosdk.constants.PICO_STATUS; the manual only names them
# and points to PicoStatus.h (PG §4.1). tests/test_fake_resource.py checks every entry.
# `PICO_HANDLE_INVALID` (spelled so in PG §3.2, §3.5, §3.7) is not a header name; the header
# has only PICO_INVALID_HANDLE, which the fake returns.
STATUS: Mapping[str, int] = {
    "PICO_OK": 0x00000000,  # PicoStatus.h via picosdk.constants
    "PICO_NOT_FOUND": 0x00000003,  # PicoStatus.h via picosdk.constants
    "PICO_NOT_RESPONDING": 0x00000007,  # PicoStatus.h via picosdk.constants
    "PICO_INVALID_HANDLE": 0x0000000C,  # PicoStatus.h via picosdk.constants
    "PICO_INVALID_PARAMETER": 0x0000000D,  # PicoStatus.h via picosdk.constants
    "PICO_INVALID_TIMEBASE": 0x0000000E,  # PicoStatus.h via picosdk.constants
    "PICO_INVALID_VOLTAGE_RANGE": 0x0000000F,  # PicoStatus.h via picosdk.constants
    "PICO_INVALID_CHANNEL": 0x00000010,  # PicoStatus.h via picosdk.constants
    "PICO_INVALID_TRIGGER_CHANNEL": 0x00000011,  # PicoStatus.h via picosdk.constants
    "PICO_TOO_MANY_SAMPLES": 0x0000001D,  # PicoStatus.h via picosdk.constants
    "PICO_TOO_MANY_SEGMENTS": 0x0000001E,  # PicoStatus.h via picosdk.constants
    "PICO_NO_SAMPLES_AVAILABLE": 0x00000025,  # PicoStatus.h via picosdk.constants
    "PICO_SEGMENT_OUT_OF_RANGE": 0x00000026,  # PicoStatus.h via picosdk.constants
    "PICO_BUSY": 0x00000027,  # PicoStatus.h via picosdk.constants
    "PICO_STARTINDEX_INVALID": 0x00000028,  # PicoStatus.h via picosdk.constants
    "PICO_INVALID_INFO": 0x00000029,  # PicoStatus.h via picosdk.constants
    "PICO_INFO_UNAVAILABLE": 0x0000002A,  # PicoStatus.h via picosdk.constants
    "PICO_DRIVER_FUNCTION": 0x00000043,  # PicoStatus.h via picosdk.constants
    "PICO_INVALID_COUPLING": 0x00000045,  # PicoStatus.h via picosdk.constants
    "PICO_RATIO_MODE_NOT_SUPPORTED": 0x00000047,  # PicoStatus.h via picosdk.constants
}

_OK = STATUS["PICO_OK"]
_INVALID_HANDLE = STATUS["PICO_INVALID_HANDLE"]
_INVALID_CHANNEL = STATUS["PICO_INVALID_CHANNEL"]
_INVALID_PARAMETER = STATUS["PICO_INVALID_PARAMETER"]
_INVALID_TIMEBASE = STATUS["PICO_INVALID_TIMEBASE"]
_SEGMENT_OUT_OF_RANGE = STATUS["PICO_SEGMENT_OUT_OF_RANGE"]

# Enum name tables, validated by name (the manual gives no numeric values, PG §4.2).
# Channel name -> position in the `overflow` bit field, bit 0 = channel A (PG §3.18).
CHANNELS: Mapping[str, int] = {
    "PS2000A_CHANNEL_A": 0,  # PG §3.39, §3.18
    "PS2000A_CHANNEL_B": 1,  # PG §3.39
    "PS2000A_CHANNEL_C": 2,  # PG §3.39
    "PS2000A_CHANNEL_D": 3,  # PG §3.39
}
COUPLINGS: tuple[str, ...] = (
    "PS2000A_AC",  # PG §3.39
    "PS2000A_DC",  # PG §3.39
)
# Range name -> full-scale volts. ASSUMPTION(hw): the fake offers all ten ranges the manual
# lists (§3.39) on every channel; the 2207B MSO may offer fewer (PG §2.3 "subject to the
# device specification").
RANGE_VOLTS: Mapping[str, float] = {
    "PS2000A_20MV": 0.020,  # PG §3.39
    "PS2000A_50MV": 0.050,  # PG §3.39
    "PS2000A_100MV": 0.100,  # PG §3.39
    "PS2000A_200MV": 0.200,  # PG §3.39
    "PS2000A_500MV": 0.500,  # PG §3.39
    "PS2000A_1V": 1.0,  # PG §3.39
    "PS2000A_2V": 2.0,  # PG §3.39
    "PS2000A_5V": 5.0,  # PG §3.39
    "PS2000A_10V": 10.0,  # PG §3.39
    "PS2000A_20V": 20.0,  # PG §3.39
}
DIRECTIONS: tuple[str, ...] = (
    "PS2000A_ABOVE",  # PG §3.56
    "PS2000A_BELOW",  # PG §3.56
    "PS2000A_RISING",  # PG §3.56
    "PS2000A_FALLING",  # PG §3.56
    "PS2000A_RISING_OR_FALLING",  # PG §3.56
)
RATIO_MODES: tuple[str, ...] = (
    "PS2000A_RATIO_MODE_NONE",  # PG §3.18, §3.18.1
    "PS2000A_RATIO_MODE_AGGREGATE",  # PG §3.18.1
    "PS2000A_RATIO_MODE_AVERAGE",  # PG §3.18.1
    "PS2000A_RATIO_MODE_DECIMATE",  # PG §3.18.1
)
_RATIO_NONE = "PS2000A_RATIO_MODE_NONE"  # PG §3.18

# ADC scaling, PG §2.3: full-scale positive 32 512 (0x7F00), full-scale negative -32 512.
MAX_ADC = 32512
MIN_ADC = -32512

_INT16_MIN, _INT16_MAX = -(2**15), 2**15 - 1  # PG §4.3
_UINT32_MAX = 2**32 - 1  # PG §4.3; timebase range "0 to 2^32 - 1" PG §3.37
_MAX_AUTO_MS = 32767  # PG §3.56: autoTrigger_ms is an int16_t

# Strings for ps2000aGetUnitInfo (PG §3.17, info codes 0..10). The manual gives an example
# per code; the values here are deterministic fake ones. PICO_VARIANT_INFO and
# PICO_BATCH_AND_SERIAL come from the unit itself.
_INFO_NAMES: tuple[str, ...] = (
    "PICO_DRIVER_VERSION",  # PG §3.17
    "PICO_USB_VERSION",  # PG §3.17
    "PICO_HARDWARE_VERSION",  # PG §3.17
    "PICO_VARIANT_INFO",  # PG §3.17
    "PICO_BATCH_AND_SERIAL",  # PG §3.17
    "PICO_CAL_DATE",  # PG §3.17
    "PICO_KERNEL_VERSION",  # PG §3.17
    "PICO_DIGITAL_HARDWARE_VERSION",  # PG §3.17
    "PICO_ANALOGUE_HARDWARE_VERSION",  # PG §3.17
    "PICO_FIRMWARE_VERSION_1",  # PG §3.17
    "PICO_FIRMWARE_VERSION_2",  # PG §3.17
)
_DRIVER_VERSION = "0.0.0.0-fake"
_FIXED_INFO: Mapping[str, str] = {
    "PICO_DRIVER_VERSION": _DRIVER_VERSION,
    "PICO_USB_VERSION": "2.0",
    "PICO_HARDWARE_VERSION": "1",
    "PICO_CAL_DATE": "01Jan26",
    "PICO_KERNEL_VERSION": "0.0-fake",
    "PICO_DIGITAL_HARDWARE_VERSION": "1",
    "PICO_ANALOGUE_HARDWARE_VERSION": "1",
    "PICO_FIRMWARE_VERSION_1": "0.0.0.0",
    "PICO_FIRMWARE_VERSION_2": "0.0.0.0",
}

_CLOCK_EDGE_TOLERANCE = 1e-9  # cycles; keeps a sample exactly on an edge on the intended side
_GLITCH_OFFSET = 7  # SPEC §6: the glitch replaces the sample at index pre + 7
_ARBITRARY_PHASE = 0.37  # SPEC §6: clock phase (cycles) when the trigger point is arbitrary


@dataclass
class ChannelConfig:
    """State stored by `ps2000aSetChannel` (PG §3.39)."""

    enabled: bool = False
    coupling: str = "PS2000A_DC"
    range: str = "PS2000A_5V"
    analog_offset: float = 0.0


@dataclass
class TriggerConfig:
    """State stored by `ps2000aSetSimpleTrigger` (PG §3.56)."""

    enabled: bool = False
    source: str = "PS2000A_CHANNEL_A"
    threshold: int = 0
    direction: str = "PS2000A_RISING"
    delay: int = 0
    auto_trigger_ms: int = 0


@dataclass
class FakeUnit:
    """One opened unit. Public so tests can inspect what the plug configured."""

    handle: int
    serial: str
    variant: str
    n_channels: int
    channels: dict[str, ChannelConfig] = field(default_factory=dict)
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    # Weak references: the real driver keeps a raw pointer (PG §3.40), not a reference, so a
    # registered array that the caller let die is a dangling pointer there.
    buffers: dict[str, "weakref.ReferenceType[npt.NDArray[np.int16]]"] = field(default_factory=dict)
    armed: bool = False  # RunBlock called, Stop not yet (PG §3.65)
    has_run: bool = False  # a RunBlock has been accepted
    polls_left: int = 0  # IsReady polls that still return 0
    pre: int = 0
    post: int = 0
    timebase: int = 0
    run_channels: dict[str, ChannelConfig] = field(default_factory=dict)  # snapshot at RunBlock
    phase: float = 0.0  # clock phase in cycles chosen by the trigger at RunBlock
    never_ready: bool = False  # the trigger can never fire and no auto trigger is set
    data_valid: bool = False  # cleared by a settings change after RunBlock (PG §2.6.1)


class FakePs2000a:
    """Hardware-free implementation of the `Ps2000aApi` Protocol (SPEC section 3.1).

    The fake's signal is a square wave "clock" between 0 V and `clock_v` at `clock_hz`
    (or a sample-index `ramp`), put on every enabled channel. The clock shape is to be
    measured later on hardware against the SDG. `defect` models a faulty measurement chain
    for negative tests.
    """

    def __init__(
        self,
        serials: Sequence[str] = ("FAKE0/001",),
        variant: str = "2207BMSO",
        signal: Literal["clock", "ramp"] = "clock",
        clock_hz: float = 1000.0,
        clock_v: float = 1.0,
        defect: Literal["shift", "gain", "glitch"] | None = None,
        memory_samples: int = 65536,
        max_rate_hz: float = 1e9,
        ready_after: int = 2,
        adc_bits: int = 16,
        noise_codes: float = 0.0,
        noise_seed: int = 0,
        per_channel_scale: Mapping[str, float] | None = None,
        short_read: int | None = None,
        info_unavailable: Iterable[str] = (),
    ) -> None:
        problems: list[str] = []
        if len(set(serials)) != len(serials):
            problems.append("serials must be distinct")
        if signal not in ("clock", "ramp"):
            problems.append(f"signal must be 'clock' or 'ramp', not {signal!r}")
        if defect not in (None, "shift", "gain", "glitch"):
            problems.append(f"defect must be None, 'shift', 'gain' or 'glitch', not {defect!r}")
        if not clock_hz > 0:
            problems.append("clock_hz must be > 0")
        if memory_samples <= 0:
            problems.append("memory_samples must be > 0")
        if not max_rate_hz > 0:
            problems.append("max_rate_hz must be > 0")
        if ready_after < 0:
            problems.append("ready_after must be >= 0")
        if not 1 <= adc_bits <= 16:
            problems.append("adc_bits must be in 1..16")
        if not (math.isfinite(noise_codes) and noise_codes >= 0):
            problems.append("noise_codes must be a finite number >= 0")
        scale = dict(per_channel_scale or {})
        for channel, factor in scale.items():
            if channel not in CHANNELS:
                problems.append(f"per_channel_scale: unknown channel {channel!r}")
            elif not (math.isfinite(factor) and factor > 0):
                problems.append(f"per_channel_scale[{channel!r}] must be a finite number > 0")
        if short_read is not None and short_read < 0:
            problems.append("short_read must be None or >= 0")
        unavailable = set(info_unavailable)
        if not unavailable <= set(_INFO_NAMES):
            problems.append(
                f"info_unavailable: unknown info names {sorted(unavailable - set(_INFO_NAMES))}"
            )
        if problems:
            raise ValueError("invalid FakePs2000a arguments: " + "; ".join(problems))
        self._serials = tuple(serials)
        self.variant = variant
        self.signal = signal
        self.clock_hz = float(clock_hz)
        self.clock_v = float(clock_v)
        self.defect = defect
        # ASSUMPTION(hw): memory per segment, maximum sampling rate and the ranges offered
        # are guesses for a 2207B MSO (PG §2.7 and §2.6.1 give no model figures); the
        # owner corrects them after hardware session 1.
        self.memory_samples = int(memory_samples)
        self.max_rate_hz = float(max_rate_hz)
        self.ready_after = int(ready_after)
        # Strictness knobs (review R1): quantisation of the codes, noise (standard deviation in
        # ADC codes, seeded), a different clock amplitude per channel so that a swap of two
        # channels' data is detectable, a short GetValues, and info strings that are missing.
        self.adc_bits = int(adc_bits)
        self.noise_codes = float(noise_codes)
        self.per_channel_scale: dict[str, float] = scale
        self.short_read = short_read
        self.info_unavailable: set[str] = unavailable
        self._rng = np.random.default_rng(noise_seed)
        self.log: list[tuple[str, tuple[object, ...]]] = []
        self.reject: dict[str, str] = {}  # function name -> STATUS name, sticky
        self.units: dict[int, FakeUnit] = {}
        self.closed_handles: list[int] = []
        self._next_handle = 1  # handles start at 1 and are never reused (PG §3.32: > 0)

    # -- helpers ---------------------------------------------------------------------------

    def _begin(self, name: str, *args: object) -> int | None:
        """Log the call, then return the status `reject` asks for (None: run the call).

        Numpy arguments are logged as `("ndarray", id, len)`, never as the array, so the log
        does not keep a registered buffer alive.
        """
        self.log.append(
            (
                name,
                tuple(("ndarray", id(a), len(a)) if isinstance(a, np.ndarray) else a for a in args),
            )
        )
        status_name = self.reject.get(name)
        if status_name is None:
            return None
        return STATUS[status_name]

    def _unopened(self) -> list[str]:
        open_serials = {unit.serial for unit in self.units.values()}
        return [s for s in self._serials if s not in open_serials]

    def _n_analog_channels(self) -> int:
        # ASSUMPTION(hw) Q21: the variant string format is not in the manual (PG §3.17 example
        # "2206"), nor is the channel count of a model (PG §3.17 returns only the string). The
        # fake treats "24..." (2405A..2408B) as four channels and anything else as two.
        return 4 if self.variant.startswith("24") else 2

    @staticmethod
    def _channel_status(unit: FakeUnit, channel: str) -> int:
        if channel not in CHANNELS:
            return _INVALID_CHANNEL  # PG §3.39 Returns
        if CHANNELS[channel] >= unit.n_channels:
            # ASSUMPTION(hw): channel C/D on a 2-channel model gives PICO_INVALID_CHANNEL
            # (PG §3.39 lists the code but does not tie it to this case).
            return _INVALID_CHANNEL
        return _OK

    @staticmethod
    def _enabled_count(channels: Mapping[str, ChannelConfig]) -> int:
        return sum(1 for c in channels.values() if c.enabled)

    def _interval_ns(self, timebase: int) -> float | None:
        """Sample interval in ns for a timebase, PG §2.7 (None: outside 0..2^32-1)."""
        if timebase < 0 or timebase > _UINT32_MAX:
            return None  # PG §3.37: timebase is "a number in the range 0 to 2^32 - 1"
        if timebase <= 2:
            # n = 0, 1, 2: 2^n / max rate (1 ns, 2 ns, 4 ns at 1 GS/s). PG §2.7
            return 2.0**timebase * 1e9 / self.max_rate_hz
        # n >= 3: (n - 2) / (max rate / 8) (125 MS/s at 1 GS/s, 62.5 MS/s at 500 MS/s). PG §2.7
        return (timebase - 2) * 8e9 / self.max_rate_hz

    def _max_samples(self, enabled: int) -> int:
        # PG §2.6.1: memory is shared between enabled channels; two get half, three or four
        # a quarter. ASSUMPTION(hw): one enabled channel (or none) gets all of it, and
        # the memory size itself is a guess; see __init__.
        if enabled <= 1:
            return self.memory_samples
        if enabled == 2:
            return self.memory_samples // 2
        return self.memory_samples // 4

    def _timebase_check(
        self, channels: Mapping[str, ChannelConfig], timebase: int
    ) -> tuple[int, float, int]:
        """Shared by GetTimebase2 and RunBlock: (status, interval_ns, max_samples)."""
        interval = self._interval_ns(timebase)
        if interval is None:
            return (_INVALID_TIMEBASE, 0.0, 0)
        enabled = self._enabled_count(channels)
        if timebase == 0 and enabled > 1:
            return (_INVALID_TIMEBASE, 0.0, 0)  # PG §2.7 footnote *: single-channel mode only
        return (_OK, interval, self._max_samples(enabled))

    # -- discovery, open, close, information ------------------------------------------------

    def ps2000aEnumerateUnits(self) -> tuple[int, int, str]:
        rejected = self._begin("ps2000aEnumerateUnits")
        if rejected is not None:
            return (rejected, 0, "")
        # PG §3.4: counts unopened units only, serials separated by commas
        unopened = self._unopened()
        return (_OK, len(unopened), ",".join(unopened))

    def ps2000aOpenUnit(self, serial: str | None) -> tuple[int, int]:
        rejected = self._begin("ps2000aOpenUnit", serial)
        if rejected is not None:
            return (rejected, 0)
        unopened = self._unopened()
        # PG §3.32: serial NULL opens the first scope found, else the one matching the string.
        # ASSUMPTION(hw): the match is exact and case-sensitive, a unit that is already open
        # is "not found", and PICO_NOT_FOUND comes with handle 0 (also for serial NULL
        # when nothing is left to open); PG §3.32 does not say how status and handle combine.
        if serial is None:
            chosen = unopened[0] if unopened else None
        else:
            chosen = serial if serial in unopened else None
        if chosen is None:
            return (STATUS["PICO_NOT_FOUND"], 0)
        handle = self._next_handle
        self._next_handle += 1
        n_channels = self._n_analog_channels()
        # ASSUMPTION(hw): after OpenUnit every channel is disabled, the trigger is off and
        # no buffer is registered; the manual does not describe the state of a fresh unit.
        channels = {name: ChannelConfig() for name, bit in CHANNELS.items() if bit < n_channels}
        self.units[handle] = FakeUnit(
            handle=handle,
            serial=chosen,
            variant=self.variant,
            n_channels=n_channels,
            channels=channels,
        )
        return (_OK, handle)

    def ps2000aCloseUnit(self, handle: int) -> tuple[int]:
        rejected = self._begin("ps2000aCloseUnit", handle)
        if rejected is not None:
            return (rejected,)
        if handle not in self.units:
            return (_INVALID_HANDLE,)  # PG §3.2 (spelled PICO_HANDLE_INVALID there)
        # PG §3.2: shuts the unit down. ASSUMPTION(hw): closing does not need a prior Stop
        # (PG §2.2 steps 7, 8 show Stop first, but the manual does not require it); the
        # serial becomes unopened again (PG §3.4).
        del self.units[handle]
        self.closed_handles.append(handle)
        return (_OK,)

    def ps2000aGetUnitInfo(self, handle: int, info: str) -> tuple[int, str]:
        rejected = self._begin("ps2000aGetUnitInfo", handle, info)
        if rejected is not None:
            return (rejected, "")
        unit = self.units.get(handle)
        if unit is None:
            # PG §3.17: "If an invalid handle is passed, only the driver versions can be
            # read." ASSUMPTION(hw): "driver versions" means PICO_DRIVER_VERSION only.
            if info == "PICO_DRIVER_VERSION":
                return (_OK, _DRIVER_VERSION)
            return (_INVALID_HANDLE, "")
        if info not in _INFO_NAMES:
            return (STATUS["PICO_INVALID_INFO"], "")  # PG §3.17 Returns
        if info in self.info_unavailable:
            return (STATUS["PICO_INFO_UNAVAILABLE"], "")  # PG §3.17 Returns
        if info == "PICO_VARIANT_INFO":
            return (_OK, unit.variant)
        if info == "PICO_BATCH_AND_SERIAL":
            return (_OK, unit.serial)
        return (_OK, _FIXED_INFO[info])

    def ps2000aPingUnit(self, handle: int) -> tuple[int]:
        rejected = self._begin("ps2000aPingUnit", handle)
        if rejected is not None:
            return (rejected,)
        if handle not in self.units:
            return (_INVALID_HANDLE,)  # PG §3.35
        return (_OK,)

    def ps2000aFlashLed(self, handle: int, start: int) -> tuple[int]:
        rejected = self._begin("ps2000aFlashLed", handle, start)
        if rejected is not None:
            return (rejected,)
        if handle not in self.units:
            return (_INVALID_HANDLE,)  # PG §3.5 (spelled PICO_HANDLE_INVALID there)
        return (_OK,)

    def ps2000aMaximumValue(self, handle: int) -> tuple[int, int]:
        rejected = self._begin("ps2000aMaximumValue", handle)
        if rejected is not None:
            return (rejected, 0)
        if handle not in self.units:
            return (_INVALID_HANDLE, 0)  # PG §3.28
        return (_OK, MAX_ADC)  # PG §2.3, §3.28

    def ps2000aMinimumValue(self, handle: int) -> tuple[int, int]:
        rejected = self._begin("ps2000aMinimumValue", handle)
        if rejected is not None:
            return (rejected, 0)
        if handle not in self.units:
            return (_INVALID_HANDLE, 0)  # PG §3.30
        return (_OK, MIN_ADC)  # PG §2.3, §3.30

    # -- channel, timebase, trigger setup ---------------------------------------------------

    def ps2000aSetChannel(
        self, handle: int, channel: str, enabled: int, type: str, range: str, analogOffset: float
    ) -> tuple[int]:
        rejected = self._begin(
            "ps2000aSetChannel", handle, channel, enabled, type, range, analogOffset
        )
        if rejected is not None:
            return (rejected,)
        unit = self.units.get(handle)
        if unit is None:
            return (_INVALID_HANDLE,)  # PG §3.39 Returns
        status = self._channel_status(unit, channel)
        if status != _OK:
            return (status,)
        if type not in COUPLINGS:
            return (STATUS["PICO_INVALID_COUPLING"],)  # PG §3.39 Returns
        if range not in RANGE_VOLTS:
            return (STATUS["PICO_INVALID_VOLTAGE_RANGE"],)  # PG §3.39 Returns
        # PG §3.39: any non-zero `enabled` enables. ASSUMPTION(hw): a disabled channel
        # still needs a valid coupling and range (the manual gives no "don't care" values).
        # analogOffset is stored only; analog offset is outside phase 1.
        unit.channels[channel] = ChannelConfig(
            enabled=bool(enabled), coupling=type, range=range, analog_offset=float(analogOffset)
        )
        # PG §2.6.1 "Data retention": the data is lost when the settings are changed.
        # ASSUMPTION(hw) Q35: that includes channel settings changed after RunBlock.
        unit.data_valid = False
        return (_OK,)

    def ps2000aGetTimebase2(
        self, handle: int, timebase: int, noSamples: int, oversample: int, segmentIndex: int
    ) -> tuple[int, float, int]:
        rejected = self._begin(
            "ps2000aGetTimebase2", handle, timebase, noSamples, oversample, segmentIndex
        )
        if rejected is not None:
            return (rejected, 0.0, 0)
        unit = self.units.get(handle)
        if unit is None:
            return (_INVALID_HANDLE, 0.0, 0)  # PG §3.13 Returns
        if segmentIndex != 0:
            # PG §3.29: one segment by default; PG §3.13 lists PICO_SEGMENT_OUT_OF_RANGE
            return (_SEGMENT_OUT_OF_RANGE, 0.0, 0)
        # `oversample` is "not used" (PG §3.13) and ignored.
        # ASSUMPTION(hw): a negative noSamples is PICO_INVALID_PARAMETER (PG §3.13 lists the
        # code without saying when).
        if noSamples < 0:
            return (_INVALID_PARAMETER, 0.0, 0)
        # PG §3.13: depends on the channels enabled by the last SetChannel calls.
        # ASSUMPTION(hw): with no channel enabled the memory is not shared (one channel).
        status, interval_ns, max_samples = self._timebase_check(unit.channels, timebase)
        if status != _OK:
            # ASSUMPTION(hw): the out arguments are 0 when the status is
            # PICO_INVALID_TIMEBASE (PG §3.13 does not say what they hold).
            return (status, 0.0, 0)
        # PG §3.14: the interval is a C float.
        interval_f32 = float(np.float32(interval_ns))
        if noSamples > max_samples:
            # ASSUMPTION(hw): both outputs are still filled in with PICO_TOO_MANY_SAMPLES
            # (PG §3.13 lists the code; the manual does not say what the outputs hold).
            return (STATUS["PICO_TOO_MANY_SAMPLES"], interval_f32, max_samples)
        return (_OK, interval_f32, max_samples)

    def ps2000aSetSimpleTrigger(
        self,
        handle: int,
        enable: int,
        source: str,
        threshold: int,
        direction: str,
        delay: int,
        autoTrigger_ms: int,
    ) -> tuple[int]:
        rejected = self._begin(
            "ps2000aSetSimpleTrigger",
            handle,
            enable,
            source,
            threshold,
            direction,
            delay,
            autoTrigger_ms,
        )
        if rejected is not None:
            return (rejected,)
        unit = self.units.get(handle)
        if unit is None:
            return (_INVALID_HANDLE,)  # PG §3.56 Returns
        if not enable:
            # PG §3.56: zero disables the trigger. ASSUMPTION(hw) Q29: the other arguments are
            # ignored when enable is 0.
            unit.trigger = TriggerConfig()
            unit.data_valid = False  # PG §2.6.1 "Data retention", ASSUMPTION(hw) Q35
            return (_OK,)
        status = self._channel_status(unit, source)
        if status != _OK:
            return (status,)
        # ASSUMPTION(hw): an unknown direction, a threshold outside int16, a negative or
        # above-int16 autoTrigger_ms and a delay outside uint32 give PICO_INVALID_PARAMETER
        # (PG §3.56 lists the code without saying when; types per §3.56 and §4.3).
        if direction not in DIRECTIONS:
            return (_INVALID_PARAMETER,)
        if not _INT16_MIN <= threshold <= _INT16_MAX:
            return (_INVALID_PARAMETER,)
        if not 0 <= autoTrigger_ms <= _MAX_AUTO_MS:
            return (_INVALID_PARAMETER,)
        if not 0 <= delay <= _UINT32_MAX:
            return (_INVALID_PARAMETER,)
        if not unit.channels[source].enabled:
            # ASSUMPTION(hw): a source that is not enabled gives PICO_INVALID_TRIGGER_CHANNEL
            # here (PG §3.37 lists the code under RunBlock, §3.56 does not list it).
            return (STATUS["PICO_INVALID_TRIGGER_CHANNEL"],)
        # ASSUMPTION(hw): `delay` and `autoTrigger_ms` are stored but do not change the
        # generated data (the manual does not say where the trigger sample sits, PG §3.37).
        unit.trigger = TriggerConfig(
            enabled=True,
            source=source,
            threshold=int(threshold),
            direction=direction,
            delay=int(delay),
            auto_trigger_ms=int(autoTrigger_ms),
        )
        unit.data_valid = False  # PG §2.6.1 "Data retention", ASSUMPTION(hw) Q35
        return (_OK,)

    def ps2000aSetDataBuffer(
        self, handle: int, channel: str, buffer: npt.NDArray[np.int16], segmentIndex: int, mode: str
    ) -> tuple[int]:
        rejected = self._begin("ps2000aSetDataBuffer", handle, channel, buffer, segmentIndex, mode)
        if rejected is not None:
            return (rejected,)
        unit = self.units.get(handle)
        if unit is None:
            return (_INVALID_HANDLE,)  # PG §3.40 Returns
        status = self._channel_status(unit, channel)
        if status != _OK:
            return (status,)
        if segmentIndex != 0:
            return (_SEGMENT_OUT_OF_RANGE,)  # PG §3.40 Returns, §3.29 one segment
        # ASSUMPTION(hw): buffer must be a non-empty 1-D int16 array (bufferLth is
        # len(buffer), PG §3.40 does not say whether that is samples or bytes) and an unknown
        # mode name is PICO_INVALID_PARAMETER.
        if mode not in RATIO_MODES:
            return (_INVALID_PARAMETER,)
        if not isinstance(buffer, np.ndarray) or buffer.dtype != np.int16 or buffer.ndim != 1:
            return (_INVALID_PARAMETER,)
        if buffer.size == 0:
            return (_INVALID_PARAMETER,)
        if mode != _RATIO_NONE:
            # Fake limitation (phase 1 is raw data only). PG §3.40: SetDataBuffer does not
            # support aggregation (use SetDataBuffers); downsampling is not simulated.
            return (STATUS["PICO_RATIO_MODE_NOT_SUPPORTED"],)
        # PG §3.40: tells the driver where to store the data. The array is kept by weak
        # reference and written in place by GetValues; if the caller lets it die, GetValues
        # fails (the driver's pointer would dangle). ASSUMPTION(hw) Q18: a buffer survives later
        # SetChannel and RunBlock calls (PG §2.6.1.1 step 7: "outside the loop").
        unit.buffers[channel] = weakref.ref(buffer)
        return (_OK,)

    # -- run, wait, retrieve, stop ----------------------------------------------------------

    def ps2000aRunBlock(
        self,
        handle: int,
        noOfPreTriggerSamples: int,
        noOfPostTriggerSamples: int,
        timebase: int,
        oversample: int,
        segmentIndex: int,
    ) -> tuple[int, int]:
        rejected = self._begin(
            "ps2000aRunBlock",
            handle,
            noOfPreTriggerSamples,
            noOfPostTriggerSamples,
            timebase,
            oversample,
            segmentIndex,
        )
        if rejected is not None:
            return (rejected, 0)
        unit = self.units.get(handle)
        if unit is None:
            return (_INVALID_HANDLE, 0)  # PG §3.37 Returns
        if segmentIndex != 0:
            return (_SEGMENT_OUT_OF_RANGE, 0)  # PG §3.37 Returns, §3.29 one segment
        pre, post = noOfPreTriggerSamples, noOfPostTriggerSamples
        # ASSUMPTION(hw): negative counts or no sample at all give PICO_INVALID_PARAMETER
        # (PG §3.37 lists the code without saying when).
        if pre < 0 or post < 0 or pre + post == 0:
            return (_INVALID_PARAMETER, 0)
        if self._enabled_count(unit.channels) == 0:
            # ASSUMPTION(hw): running with no channel enabled is PICO_INVALID_CHANNEL (PG §3.37
            # lists the code without saying when).
            return (_INVALID_CHANNEL, 0)
        status, interval_ns, max_samples = self._timebase_check(unit.channels, timebase)
        if status != _OK:
            return (status, 0)  # PICO_INVALID_TIMEBASE, PG §3.37 Returns
        trigger = unit.trigger
        if trigger.enabled and not unit.channels[trigger.source].enabled:
            return (STATUS["PICO_INVALID_TRIGGER_CHANNEL"], 0)  # PG §3.37 Returns
        if pre + post > max_samples:
            # PG §3.37: the total must not exceed the segment size.
            return (STATUS["PICO_TOO_MANY_SAMPLES"], 0)
        # A new run discards the previous data (PG §2.6.1 "Data retention"). The channel
        # settings are snapshotted for generating the data; a later SetChannel or
        # SetSimpleTrigger makes the data invalid anyway (`data_valid`, ASSUMPTION(hw) Q18).
        unit.armed = True
        unit.has_run = True
        unit.polls_left = self.ready_after
        unit.pre, unit.post, unit.timebase = pre, post, timebase
        unit.run_channels = {
            name: ChannelConfig(c.enabled, c.coupling, c.range, c.analog_offset)
            for name, c in unit.channels.items()
        }
        unit.phase, unit.never_ready = self._trigger_plan(unit)
        unit.data_valid = True
        # PG §3.37: timeIndisposedMs is the time spent collecting, without any auto trigger
        # timeout. Rounded before ceil so float noise cannot add a millisecond.
        time_ms = math.ceil(round((pre + post) * interval_ns / 1e6, 9))
        return (_OK, time_ms)

    def _amplitude(self, channel: str) -> float:
        """Clock amplitude in volts on `channel` (`clock_v` times its `per_channel_scale`)."""
        return self.clock_v * self.per_channel_scale.get(channel, 1.0)

    def _span(self, amplitude: float) -> tuple[float, float]:
        """Lowest and highest volts the generated signal reaches, defects included."""
        low = 0.0
        high = amplitude * 999 / 1000 if self.signal == "ramp" else amplitude
        if self.defect == "shift":
            low, high = low + 0.1 * amplitude, high + 0.1 * amplitude
        elif self.defect == "gain":
            high *= 1.1
        return low, high

    def _trigger_plan(self, unit: FakeUnit) -> tuple[float, bool]:
        """(clock phase in cycles, never_ready) that the trigger settings give at RunBlock.

        PG §3.56 gives a direction and a threshold but not where the trigger sample sits;
        ASSUMPTION(hw) Q30: it is sample index `pre` (PG §3.37 only says pre + post samples are
        returned). With RISING (also ABOVE, RISING_OR_FALLING) the first sample at or above the
        threshold after being below it is index `pre`: phase 0; FALLING (also BELOW) is the
        mirror image: phase 0.5. The threshold is honoured, in ADC codes of the source channel:
        an edge exists only if the signal has samples below and at-or-above it. When no edge
        exists the trigger cannot fire: with `auto_trigger_ms == 0` the capture never becomes
        ready (PG §3.56: "wait indefinitely"), otherwise the phase is arbitrary (0.37, fixed
        so that tests are deterministic). A level condition that is already true (ABOVE with the
        signal always above, BELOW with it always below) fires at once, also at phase 0.37.
        ASSUMPTION(hw) Q11: what a real unit captures after an auto-trigger timeout is open.
        """
        trigger = unit.trigger
        if not trigger.enabled:
            return 0.0, False  # SPEC §6: without a trigger the phase is fixed at 0
        range_v = RANGE_VOLTS[unit.channels[trigger.source].range]
        low_v, high_v = self._span(self._amplitude(trigger.source))
        low = int(np.clip(round(low_v / range_v * MAX_ADC), MIN_ADC, MAX_ADC))  # PG §2.3
        high = int(np.clip(round(high_v / range_v * MAX_ADC), MIN_ADC, MAX_ADC))
        threshold = trigger.threshold
        falling = trigger.direction in ("PS2000A_FALLING", "PS2000A_BELOW")
        if low < threshold <= high:  # samples below and at-or-above: an edge exists
            return (0.5 if falling else 0.0), False
        if trigger.direction == "PS2000A_ABOVE" and threshold <= low:
            return _ARBITRARY_PHASE, False  # always above: fires at once
        if trigger.direction == "PS2000A_BELOW" and threshold > high:
            return _ARBITRARY_PHASE, False  # always below: fires at once
        if trigger.auto_trigger_ms == 0:
            return 0.0, True  # PG §3.56: waits indefinitely for a trigger that cannot come
        return _ARBITRARY_PHASE, False  # auto trigger timeout: arbitrary but deterministic

    def ps2000aIsReady(self, handle: int) -> tuple[int, int]:
        rejected = self._begin("ps2000aIsReady", handle)
        if rejected is not None:
            return (rejected, 0)
        unit = self.units.get(handle)
        if unit is None:
            return (_INVALID_HANDLE, 0)  # PG §3.26 Returns
        if not unit.armed:
            # ASSUMPTION(hw): with nothing running the call returns (PICO_OK, 0); PG §3.26
            # does not say (it lists PICO_NO_SAMPLES_AVAILABLE and PICO_CANCELLED unexplained).
            return (_OK, 0)
        if unit.never_ready:
            return (_OK, 0)  # PG §3.56: still waiting for a trigger that cannot come
        if unit.polls_left > 0:
            unit.polls_left -= 1  # PG §3.26: zero while the device is still collecting
            return (_OK, 0)
        return (_OK, 1)  # PG §3.26: non-zero, GetValues can be used

    def ps2000aGetValues(
        self,
        handle: int,
        startIndex: int,
        noOfSamples: int,
        downSampleRatio: int,
        downSampleRatioMode: str,
        segmentIndex: int,
    ) -> tuple[int, int, int]:
        rejected = self._begin(
            "ps2000aGetValues",
            handle,
            startIndex,
            noOfSamples,
            downSampleRatio,
            downSampleRatioMode,
            segmentIndex,
        )
        if rejected is not None:
            return (rejected, 0, 0)
        unit = self.units.get(handle)
        if unit is None:
            return (_INVALID_HANDLE, 0, 0)  # PG §3.18 Returns
        if segmentIndex != 0:
            return (_SEGMENT_OUT_OF_RANGE, 0, 0)  # PG §3.18 Returns, §3.29 one segment
        if downSampleRatioMode not in RATIO_MODES:
            return (_INVALID_PARAMETER, 0, 0)  # ASSUMPTION(hw): status for an unknown mode name
        if downSampleRatioMode != _RATIO_NONE:
            # Fake limitation: no downsampling (phase 1). PG §3.18 lists the code.
            return (STATUS["PICO_RATIO_MODE_NOT_SUPPORTED"], 0, 0)
        # PG §3.18: RATIO_MODE_NONE ignores downSampleRatio.
        if not unit.has_run or unit.polls_left > 0 or unit.never_ready or not unit.data_valid:
            # PG §3.18: before the scope is ready "no capture will be available"; PG §2.6.1
            # "Data retention": the data is gone once the settings were changed (Q18).
            return (STATUS["PICO_NO_SAMPLES_AVAILABLE"], 0, 0)
        total = unit.pre + unit.post
        if startIndex < 0 or noOfSamples < 0:
            return (_INVALID_PARAMETER, 0, 0)  # ASSUMPTION(hw): negative arguments
        if startIndex >= total:
            return (STATUS["PICO_STARTINDEX_INVALID"], 0, 0)  # PG §3.18 Returns
        # PG §3.18: the number retrieved is not more than requested; the data starts at
        # startIndex (measured in sample intervals from the start of the buffer).
        n = min(noOfSamples, total - startIndex)
        if self.short_read is not None:
            n = min(n, self.short_read)  # knob: the driver returns fewer samples than asked
        for registered in unit.buffers.values():
            if registered() is None:
                # The caller let a registered array die: the driver's pointer would dangle.
                # ASSUMPTION(hw) Q33: the driver may touch the buffer of any registered
                # channel, enabled or not, so a dead array anywhere is an error.
                return (_INVALID_PARAMETER, 0, 0)
        targets: list[tuple[str, npt.NDArray[np.int16]]] = []
        for name, config in unit.run_channels.items():
            # PG §3.18: one call serves all enabled channels. ASSUMPTION(hw) Q6: an enabled
            # channel without a buffer, and a buffer of a disabled channel, are left alone
            # (the manual lists PICO_BUFFERS_NOT_SET without explanation).
            ref = unit.buffers.get(name)
            buffer = None if ref is None else ref()
            if not config.enabled or buffer is None:
                continue
            if len(buffer) < n:
                # ASSUMPTION(hw) Q19: a buffer shorter than the returned samples gives
                # PICO_INVALID_PARAMETER; PG §3.40 does not say what happens.
                return (_INVALID_PARAMETER, 0, 0)
            targets.append((name, buffer))
        interval_s = self._interval_s(unit.timebase)
        step = 2 ** (16 - self.adc_bits)  # codes are multiples of this (adc_bits knob)
        overflow = 0
        for name, buffer in targets:
            range_v = RANGE_VOLTS[unit.run_channels[name].range]
            volts = self._signal(total, unit.pre, interval_s, unit.phase, self._amplitude(name))
            # PG §2.3: count = volts / range * 32 512, clipped to the ADC limits.
            codes = volts / range_v * MAX_ADC
            if self.noise_codes > 0:
                codes = codes + self._rng.normal(0.0, self.noise_codes, size=total)
            counts = np.rint(np.rint(codes / step) * step).astype(np.int64)
            counts_out = counts[startIndex : startIndex + n]
            if np.any((counts_out > MAX_ADC) | (counts_out < MIN_ADC)):
                overflow |= 1 << CHANNELS[name]  # PG §3.18: bit 0 = channel A
            clipped = np.clip(counts, MIN_ADC, MAX_ADC).astype(np.int16)
            if self.defect == "glitch" and unit.pre + _GLITCH_OFFSET < total:
                clipped[unit.pre + _GLITCH_OFFSET] = MAX_ADC  # one full-scale sample
            buffer[:n] = clipped[startIndex : startIndex + n]  # in place, never a copy
        return (_OK, n, overflow)

    def ps2000aStop(self, handle: int) -> tuple[int]:
        rejected = self._begin("ps2000aStop", handle)
        if rejected is not None:
            return (rejected,)
        unit = self.units.get(handle)
        if unit is None:
            return (_INVALID_HANDLE,)  # PG §3.65 Returns
        # PG §3.65: stops the device. SPEC §6: the data of a finished capture stays
        # (PG §2.6.1 "Data retention": lost only on a new run, changed settings, power down).
        # PG §3.65 also says "any data in the buffer will be invalid" for block mode;
        # ASSUMPTION(hw): data already captured stays readable after Stop, a capture stopped
        # before it was ready yields PICO_NO_SAMPLES_AVAILABLE.
        unit.armed = False
        return (_OK,)

    def ps2000aMemorySegments(self, handle: int, nSegments: int) -> tuple[int, int]:
        rejected = self._begin("ps2000aMemorySegments", handle, nSegments)
        if rejected is not None:
            return (rejected, 0)
        if handle not in self.units:
            return (_INVALID_HANDLE, 0)  # PG §3.29 Returns
        if nSegments < 1:
            return (_INVALID_PARAMETER, 0)  # PG §3.29: "Minimum: 1"
        if nSegments > 1:
            # Fake limitation: phase 1 uses one segment. PG §3.29 lists PICO_TOO_MANY_SEGMENTS.
            return (STATUS["PICO_TOO_MANY_SEGMENTS"], 0)
        # PG §3.29: nMaxSamples is the number of samples in each segment, the total over all
        # channels (divide by 2 for two channels, by 4 for three or four). One segment is the
        # state after ps2000aOpenUnit, so nothing changes. ASSUMPTION(hw) Q31: it equals
        # `memory_samples`, which is also what the fake gives GetTimebase2 for one channel.
        return (_OK, self.memory_samples)

    # -- signal generation ------------------------------------------------------------------

    def _interval_s(self, timebase: int) -> float:
        interval_ns = self._interval_ns(timebase)
        assert interval_ns is not None  # RunBlock accepted this timebase
        return interval_ns * 1e-9

    def _signal(
        self, total: int, pre: int, interval_s: float, phase: float, amplitude: float
    ) -> npt.NDArray[np.float64]:
        """Volts at the input for sample indices 0..total-1 (before ADC conversion)."""
        index = np.arange(total)
        if self.signal == "ramp":
            volts = index % 1000 / 1000 * amplitude
        else:
            # Square wave between 0 and clock_v. The time axis is (i - pre) * interval, so a
            # 1 kHz clock sampled at 1 us has a period of 1000 samples. phase 0 puts a rising
            # edge exactly at index `pre`, phase 0.5 a falling edge.
            cycles = (index - pre) * interval_s * self.clock_hz + phase
            fraction = (cycles + _CLOCK_EDGE_TOLERANCE) % 1.0
            volts = np.where(fraction < 0.5, amplitude, 0.0)
        if self.defect == "shift":
            volts = volts + 0.1 * amplitude  # DC offset error
        elif self.defect == "gain":
            volts = volts * 1.1  # gain error
        return np.asarray(volts, dtype=np.float64)
