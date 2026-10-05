"""OpenHTF plug for PicoScope 2000 Series (A API) USB oscilloscopes: single-shot block capture.

The plug is thin and data-centred. Capture conditions are a frozen `Capture`; the plug exposes
`apply_capture`, `single`, `wait_ready`, `read_waveform` and `stop`. A `Waveform` keeps the
untouched ADC counts plus the metadata needed to recompute time and volts; measurements are pure
functions in `measure.py`.

Every driver call goes through the `Ps2000aApi` seam of `driver.py` and carries a manual citation
(`# PG §x.y`, ps2000apg.en-12, transcribed in `docs/api_reference.md`). Behaviour the manual
leaves open is marked in the source as an hardware assumption naming the item N of "Open
questions for hardware verification" of that file; the fake mirrors every such choice.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any, NamedTuple

import numpy as np
import numpy.typing as npt
from openhtf.plugs import BasePlug
from openhtf.util import configuration

from .capture import CHANNEL_NAMES, COUPLINGS, DIRECTIONS, RANGES, Capture
from .driver import PicosdkApi, Ps2000aApi, status_code, status_name
from .units import ns

__all__ = [
    "CONF",
    "CaptureError",
    "PicoError",
    "PicoScope2000Plug",
    "Waveform",
    "WaveformMeta",
    "waveform_from_raw",
]

CONF = configuration.CONF


def _declare(name: str, default_value: object, description: str) -> None:
    """Declare a CONF key once; a module reload must not raise `KeyAlreadyDeclaredError`."""
    try:
        CONF.declare(name, default_value=default_value, description=description)
    except configuration.KeyAlreadyDeclaredError:
        pass


# Declared at import; set values with ``CONF.load(...)`` only after importing this module.
_declare(
    "picoscope_2000_serial",
    None,
    "Serial number of the PicoScope to open (None: the first unit found)",
)
_declare(
    "picoscope_2000_timeout_s",
    10.0,
    "Default time in seconds wait_ready() waits for the capture to finish "
    "(the capture's own time_indisposed_ms is added)",
)

_PICO_OK = "PICO_OK"  # PG §4.1
_INFO_NAMES: tuple[str, ...] = (  # PG §3.17, info codes 0..10
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

# Arguments for a channel that is not captured. ASSUMPTION(hw): any valid coupling/range is
# accepted for a disabled channel; the manual gives no "don't care" values (open question 28).
_DISABLED_COUPLING = "PS2000A_DC"  # PG §3.39
_DISABLED_RANGE = "PS2000A_1V"  # PG §3.39
_ANALOG_OFFSET = 0.0  # PG §3.39: analog offset is outside phase 1
# Trigger switched off. ASSUMPTION(hw): with enable = 0 the other arguments are ignored
# (open question 29).
_NO_TRIGGER_SOURCE = "PS2000A_CHANNEL_A"  # PG §3.56
_NO_TRIGGER_DIRECTION = "PS2000A_RISING"  # PG §3.56
_RATIO_NONE = "PS2000A_RATIO_MODE_NONE"  # PG §3.18, §3.40: raw data, the ratio is ignored
# ASSUMPTION(hw) Q34 (proposed, not yet in docs/api_reference.md): with RATIO_MODE_NONE the
# manual says the ratio is ignored (PG §3.18); 1 is sent and is assumed to be accepted.
_DOWNSAMPLE_RATIO = 1
_SEGMENT = 0  # PG §3.29: one memory segment in phase 1
# ASSUMPTION(hw): 0 is a safe value for `oversample`, which the manual calls "not used"
# in §3.14 and §3.37 (open question 12).
_OVERSAMPLE = 0

_MAX_PROBES_AFTER_VALID = 8  # SPEC §4 step 2: cap of the timebase search after a valid probe
_MAX_TIMEBASE = 2**32 - 1  # PG §3.37: timebase is "a number in the range 0 to 2^32 - 1"
_INTERVAL_REL_TOL = 1e-6  # SPEC §4 step 2: the driver returns a C float (PG §3.14)
_ALL_CHANNELS = (1, 2, 3, 4)  # PG §3.39: channels A..D


class PicoError(RuntimeError):
    """A driver call did not return `PICO_OK` (PG §4.1)."""

    def __init__(self, function: str, status: int, name: str, detail: str = "") -> None:
        # `args` holds the constructor arguments, so copy and pickle rebuild the exception.
        super().__init__(function, status, name, detail)
        self.function = function
        self.status = status
        self.name = name
        self.detail = detail

    def __str__(self) -> str:
        message = f"{self.function} returned {self.name} (0x{self.status & 0xFFFFFFFF:08X})"
        if self.detail:
            message += f": {self.detail}"
        return message


class CaptureError(RuntimeError):
    """`apply_capture` problem the driver did not reject (too many samples, no timebase)."""


class WaveformMeta(NamedTuple):
    """Everything needed to recompute time and volts from `Waveform.raw`."""

    channel: int
    range_v: float
    coupling: str
    max_adc: int
    sample_interval_s: float
    pre_samples: int
    timebase: int
    overflow: bool
    serial: str
    variant: str


class Waveform(NamedTuple):
    """One channel of one capture: untouched ADC counts plus derived seconds and volts."""

    t: npt.NDArray[np.float64]  # seconds, t == 0 at the first post-trigger sample
    v: npt.NDArray[np.float64]  # volts
    raw: npt.NDArray[np.int16]  # untouched ADC counts
    meta: WaveformMeta


def waveform_from_raw(raw: npt.NDArray[np.int16], meta: WaveformMeta) -> Waveform:
    """Build a `Waveform`: keep `raw`, recompute `t` and `v` from `meta`."""
    if not isinstance(raw, np.ndarray) or raw.dtype != np.int16:
        dtype = getattr(raw, "dtype", type(raw).__name__)
        raise ValueError(f"raw must be a numpy int16 array (ADC counts), got {dtype}")
    # ASSUMPTION(hw) Q30: the trigger point is sample index pre_samples; PG §3.37 says the
    # maximum number returned is pre + post but not where the trigger sample sits.
    t = (np.arange(len(raw)) - meta.pre_samples) * meta.sample_interval_s
    v = raw.astype(np.float64) * (
        meta.range_v / meta.max_adc
    )  # PG §2.3: volts = count * range / max
    return Waveform(t=np.asarray(t, dtype=np.float64), v=v, raw=raw, meta=meta)


def _is(status: int, name: str) -> bool:
    return status_name(status) == name


def _check(function: str, status: int) -> None:
    """Raise `PicoError` unless `status` is `PICO_OK` (PG §4.1)."""
    if not _is(status, _PICO_OK):
        raise PicoError(function, status, status_name(status))


def _format_arg(value: object) -> str:
    if isinstance(value, np.ndarray):
        return f"<{value.dtype}[{value.size}]>"
    return repr(value)


def _at_least(interval: float, requested: float) -> bool:
    """`interval >= requested`, tolerating the C float rounding of PG §3.14."""
    return interval >= requested or math.isclose(interval, requested, rel_tol=_INTERVAL_REL_TOL)


def _estimate_timebase(interval_s: float) -> int:
    """First guess of the timebase for a sample interval, from the 1 GS/s table of PG §2.7."""
    # ASSUMPTION(hw) Q1: the 2207B MSO is a 1 GS/s model; the search in apply_capture makes the
    # result correct either way.
    if interval_s <= 1 * ns:
        return 0  # PG §2.7: n = 0 is 1 ns
    if interval_s <= 2 * ns:
        return 1  # PG §2.7: n = 1 is 2 ns
    if interval_s <= 4 * ns:
        return 2  # PG §2.7: n = 2 is 4 ns
    return round(interval_s * 125e6) + 2  # PG §2.7: n >= 3 is (n - 2) / 125 MS/s


class _TimebaseResult(NamedTuple):
    interval_s: float
    max_samples: int


class PicoScope2000Plug(BasePlug):  # type: ignore[misc]  # OpenHTF is untyped
    """Single-shot block capture on one PicoScope 2000 Series (A API) unit.

    Typical flow: `apply_capture(capture)`, `single()`, `wait_ready()`, `read_waveform(ch)`
    per channel, `stop()`. OpenHTF calls `tearDown()`, which stops any capture and closes the
    handle this plug opened.

    `serial` (constructor argument, then CONF `picoscope_2000_serial`, then None) selects the
    unit; None opens the first unit found and logs a WARNING when several are connected.
    `timeout_s` (then CONF `picoscope_2000_timeout_s`, then 10.0) is the default for
    `wait_ready`. `api=None` means the real driver through `PicosdkApi()`.
    """

    auto_placeholder = True

    def __init__(
        self,
        serial: str | None = None,
        *,
        api: Ps2000aApi | None = None,
        timeout_s: float | None = None,
    ) -> None:
        super().__init__()
        if serial is None:
            conf_serial = CONF.picoscope_2000_serial
            serial = None if conf_serial is None else str(conf_serial)
        if timeout_s is None:
            timeout_s = float(CONF.picoscope_2000_timeout_s)
        self._timeout_s: float = float(timeout_s)
        self._api: Ps2000aApi = PicosdkApi() if api is None else api
        self._handle: int | None = None
        self.info: dict[str, str] = {}
        self.max_adc: int = 0
        self.min_adc: int = 0
        self.channel_count: int = 4  # PG §3.39: channels A..D; 2 once the unit rejects C/D
        self.capture: Capture | None = None
        self.timebase: int | None = None
        self.sample_interval_s: float | None = None
        self.max_samples: int | None = None
        self.time_indisposed_ms: int = 0
        # Every array ever registered with ps2000aSetDataBuffer, by channel. The driver keeps the
        # raw pointer (PG §3.40), so an array must stay referenced for the life of the plug; an
        # entry is replaced only right after its own successful registration (SPEC §4 step 5).
        self._registered: dict[int, npt.NDArray[np.int16]] = {}
        self._armed = False
        self._ready = False
        self._stopped = False  # stop() or a timeout ended a capture whose data was never fetched
        self._values: tuple[int, int] | None = None  # (noOfSamples, overflow) of the last fetch

        status, count, serials = self._api.ps2000aEnumerateUnits()  # PG §3.4
        if _is(status, _PICO_OK):
            self.logger.info("found %d unopened unit(s): %s", count, serials)
        else:
            # Enumeration is informational: opening by serial does not depend on it.
            self.logger.warning(
                "ps2000aEnumerateUnits returned %s; continuing without the unit list",
                status_name(status),
            )
            count, serials = 0, ""
        if serial is None and count > 1:
            self.logger.warning(
                "no serial given and %d units found (%s); opening the first one. "
                "Set CONF.picoscope_2000_serial or pass serial=",
                count,
                serials,
            )

        status, handle = self._api.ps2000aOpenUnit(serial)  # PG §3.32
        if not _is(status, _PICO_OK):
            if handle > 0:
                # ASSUMPTION(hw) Q10: the manual does not say how status and handle combine; a
                # handle > 0 next to an error status may be an open unit, so it is closed.
                self._handle = handle
                self._close_unit()
            raise PicoError("ps2000aOpenUnit", status, status_name(status))
        if handle <= 0:
            # PG §3.32: handle 0 means no scope was found, -1 that the scope failed to open.
            # ASSUMPTION(hw): the manual does not say how status and handle combine; a PICO_OK
            # with such a handle is reported as PICO_NOT_FOUND (open question 10).
            reason = "no scope found" if handle == 0 else "the scope failed to open"
            raise PicoError(
                "ps2000aOpenUnit",
                status_code("PICO_NOT_FOUND"),
                "PICO_NOT_FOUND",
                f"handle {handle}: {reason} (PG §3.32)",
            )
        self._handle = handle
        try:
            for name in _INFO_NAMES:
                status, text = self._api.ps2000aGetUnitInfo(handle, name)  # PG §3.17
                if _is(status, "PICO_INFO_UNAVAILABLE") or _is(status, "PICO_INVALID_INFO"):
                    # PG §3.17 Returns: either code means "no such string"; not worth a failure
                    self.logger.warning(
                        "%s: ps2000aGetUnitInfo returned %s", name, status_name(status)
                    )
                    self.info[name] = ""
                    continue
                _check("ps2000aGetUnitInfo", status)
                self.info[name] = text
            status, self.max_adc = self._api.ps2000aMaximumValue(handle)  # PG §3.28
            _check("ps2000aMaximumValue", status)
            status, self.min_adc = self._api.ps2000aMinimumValue(handle)  # PG §3.30
            _check("ps2000aMinimumValue", status)
        except BaseException:
            # OpenHTF does not call tearDown for a plug whose constructor failed.
            self._close_unit()
            raise
        self.logger.info(
            "opened %s serial %s driver %s",
            self.variant,
            self.serial,
            self.info["PICO_DRIVER_VERSION"],
        )

    # -- identity ---------------------------------------------------------------------------

    @property
    def serial(self) -> str:
        """Batch and serial number of the open unit (`PICO_BATCH_AND_SERIAL`, PG §3.17)."""
        return self.info.get("PICO_BATCH_AND_SERIAL", "")

    @property
    def variant(self) -> str:
        """Variant of the open unit (`PICO_VARIANT_INFO`, PG §3.17)."""
        return self.info.get("PICO_VARIANT_INFO", "")

    @staticmethod
    def list_units(api: Ps2000aApi | None = None) -> list[str]:
        """Serial numbers of the unopened units (PG §3.4: comma-separated list)."""
        driver = PicosdkApi() if api is None else api
        status, _count, serials = driver.ps2000aEnumerateUnits()  # PG §3.4
        _check("ps2000aEnumerateUnits", status)
        return [s.strip() for s in serials.split(",") if s.strip()]

    # -- plumbing ---------------------------------------------------------------------------

    def _open_handle(self) -> int:
        if self._handle is None:
            raise RuntimeError("plug closed")
        return self._handle

    def _call(self, name: str, *args: object) -> tuple[Any, ...]:
        """Call one driver function, logging the call and the status at DEBUG."""
        self.logger.debug("-> %s(%s)", name, ", ".join(_format_arg(a) for a in args))
        result: tuple[Any, ...] = getattr(self._api, name)(*args)
        self.logger.debug("<- %s", status_name(result[0]))
        return result

    def _close_unit(self) -> None:
        """Close the handle, swallowing and logging any failure (constructor cleanup)."""
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            status = self._api.ps2000aCloseUnit(handle)[0]  # PG §3.2
            if not _is(status, _PICO_OK):
                self.logger.warning("ps2000aCloseUnit returned %s", status_name(status))
        except Exception:
            self.logger.warning("ps2000aCloseUnit failed", exc_info=True)

    def _forget_data(self) -> None:
        self._armed = False
        self._ready = False
        self._stopped = False
        self._values = None

    # -- capture ----------------------------------------------------------------------------

    def apply_capture(self, capture: Capture) -> None:
        """Configure channels, timebase, trigger and buffers for `capture` (SPEC §4 steps 1..6)."""
        handle = self._open_handle()
        # The driver settings change from here on: whatever was armed or fetched is stale.
        self.capture = None
        self._forget_data()
        enabled = capture.enabled()

        # Step 1: every channel, in order. Memory is shared between the enabled channels
        # (PG §2.6.1), so unused channels are disabled explicitly.
        for ch in _ALL_CHANNELS:
            name = CHANNEL_NAMES[ch]  # PG §3.39
            if ch in enabled:
                channel = capture.channel(ch)
                args = (name, 1, COUPLINGS[channel.coupling], RANGES[channel.range], _ANALOG_OFFSET)
            elif ch in (3, 4) and self.channel_count == 2:
                continue  # an earlier call showed that the unit has no such channel
            else:
                args = (name, 0, _DISABLED_COUPLING, _DISABLED_RANGE, _ANALOG_OFFSET)
            (status,) = self._call("ps2000aSetChannel", handle, *args)  # PG §3.39
            if not _is(status, _PICO_OK) and ch in (3, 4) and ch not in enabled:
                # ASSUMPTION(hw) Q21, Q33: disabling a channel the unit does not have is refused
                # (PICO_INVALID_CHANNEL in the fake; the manual does not say which status), and
                # that means a two-channel unit.
                self.logger.info(
                    "%s refused with %s while disabling it: two-channel unit",
                    name,
                    status_name(status),
                )
                self.channel_count = 2
                continue
            _check("ps2000aSetChannel", status)

        # Step 2: timebase search (PG §2.7, §3.14), step 3: the sample count must fit.
        total = capture.total_samples
        timebase, interval_s, max_samples = self._find_timebase(
            handle, total, capture.sample_interval, enabled
        )
        if total > max_samples:
            raise CaptureError(
                f"{total} samples requested (pre {capture.pre_samples} + post "
                f"{capture.post_samples}) but timebase {timebase} with channels "
                f"{list(enabled)} holds at most {max_samples}"
            )

        # Step 4: trigger (PG §3.56).
        edge = capture.trigger
        if edge is not None:
            (status,) = self._call(
                "ps2000aSetSimpleTrigger",  # PG §3.56
                handle,
                1,
                CHANNEL_NAMES[edge.source],
                capture.trigger_threshold_adc(self.max_adc),
                DIRECTIONS[edge.direction],
                edge.delay_samples,
                edge.auto_ms,
            )
        else:
            (status,) = self._call(
                "ps2000aSetSimpleTrigger",  # PG §3.56
                handle,
                0,
                _NO_TRIGGER_SOURCE,
                0,
                _NO_TRIGGER_DIRECTION,
                0,
                0,
            )
        _check("ps2000aSetSimpleTrigger", status)

        # Step 5: one int16 buffer per enabled channel (PG §3.40). ASSUMPTION(hw) Q18: buffers
        # registered before ps2000aRunBlock survive until ps2000aGetValues; Q19: bufferLth counts
        # samples. Lifetime rule: the driver keeps the raw pointer, so each array goes into
        # `_registered` right after its own successful call and is never dropped, even when a
        # later channel fails or a later capture enables fewer channels (Q33: the driver may
        # write to the buffer of a disabled channel).
        for ch in enabled:
            buffer = np.zeros(total, dtype=np.int16)
            (status,) = self._call(
                "ps2000aSetDataBuffer",  # PG §3.40
                handle,
                CHANNEL_NAMES[ch],
                buffer,
                _SEGMENT,
                _RATIO_NONE,
            )
            _check("ps2000aSetDataBuffer", status)
            self._registered[ch] = buffer

        # Step 6: the resolved state.
        self.capture = capture
        self.timebase = timebase
        self.sample_interval_s = interval_s
        self.max_samples = max_samples
        self.logger.info(
            "capture applied: channels %s, timebase %d (%g s per sample), %d samples",
            list(enabled),
            timebase,
            interval_s,
            total,
        )

    def _find_timebase(
        self, handle: int, total: int, requested_s: float, enabled: tuple[int, ...]
    ) -> tuple[int, float, int]:
        """Smallest timebase whose interval is >= `requested_s`: (n, interval_s, maxSamples).

        SPEC §4 step 2: probe the estimate (tolerating a refusal for n = 0, 1, 2), re-estimate
        from the first valid probe with the linear law of PG §2.7 (`interval = (n - 2) / rate`
        for n >= 3, in both tables), then refine by one step at a time. At most
        `_MAX_PROBES_AFTER_VALID` further `ps2000aGetTimebase2` calls.
        """
        known: dict[int, _TimebaseResult | None] = {}  # None: n is "too small" (invalid)
        after_valid = 0

        def call(n: int) -> tuple[int, _TimebaseResult | None]:
            """One GetTimebase2 call: (status, result), result None unless usable."""
            status, interval_ns, max_samples = self._call(
                "ps2000aGetTimebase2",  # PG §3.14
                handle,
                n,
                total,
                _OVERSAMPLE,
                _SEGMENT,
            )
            # ASSUMPTION(hw) Q26: on PICO_TOO_MANY_SAMPLES both outputs are filled in, so the
            # search can finish and the plug names both numbers.
            if _is(status, "PICO_TOO_MANY_SAMPLES"):
                if max_samples <= 0:
                    raise CaptureError(
                        f"{total} samples requested but ps2000aGetTimebase2 reports "
                        f"maxSamples {max_samples} for timebase {n} (PICO_TOO_MANY_SAMPLES) "
                        f"with channels {list(enabled)}"
                    )
                return status, _TimebaseResult(interval_ns * ns, int(max_samples))
            if _is(status, _PICO_OK):
                return status, _TimebaseResult(interval_ns * ns, int(max_samples))
            return status, None

        def probe(n: int) -> _TimebaseResult | None:
            """A probe after the first valid one; `n < 3` may legitimately be refused."""
            nonlocal after_valid
            if n in known:
                return known[n]
            if after_valid >= _MAX_PROBES_AFTER_VALID:
                raise CaptureError(
                    f"no timebase for a sample interval of {requested_s:g} s found within "
                    f"{_MAX_PROBES_AFTER_VALID} ps2000aGetTimebase2 calls after the first "
                    "valid one"
                )
            after_valid += 1
            status, result = call(n)
            if result is None:
                if n < 3 and _is(status, "PICO_INVALID_TIMEBASE"):
                    # ASSUMPTION(hw) Q2, Q20: a timebase the enabled channels cannot use
                    # (n = 0 with two channels, PG §2.7 footnote) is PICO_INVALID_TIMEBASE
                    # (PG §3.14 Returns) and means "n is too small".
                    self.logger.info("timebase %d rejected: %s", n, status_name(status))
                else:
                    raise PicoError("ps2000aGetTimebase2", status, status_name(status))
            known[n] = result
            return result

        # Step A: the first valid probe, from the estimate. ASSUMPTION(hw) Q2, Q20: a refusal
        # of n = 0, 1, 2 (e.g. n = 0 needs single-channel mode, PG §2.7 footnote) is skipped.
        n = min(_estimate_timebase(requested_s), _MAX_TIMEBASE)
        while True:
            status, first = call(n)
            known[n] = first
            if first is not None:
                break
            if n >= 3:
                raise PicoError("ps2000aGetTimebase2", status, status_name(status))
            self.logger.info("timebase %d rejected: %s", n, status_name(status))
            n += 1

        # Step B: linear re-estimate from the first valid probe (PG §2.7: interval is linear
        # in n - 2 for n >= 3 in both tables), then refine one step at a time.
        if first.interval_s <= 0:
            raise CaptureError(
                f"ps2000aGetTimebase2 returned a sample interval of {first.interval_s:g} s "
                f"for timebase {n}"
            )
        if n >= 3:
            n = min(
                2 + max(1, math.ceil((n - 2) * requested_s / first.interval_s - 1e-9)),
                _MAX_TIMEBASE,
            )
        found = probe(n)
        while found is None or not _at_least(found.interval_s, requested_s):  # too short: up
            if n >= _MAX_TIMEBASE:
                raise CaptureError(
                    f"a sample interval of {requested_s:g} s is longer than the slowest "
                    f"timebase {_MAX_TIMEBASE} (PG §3.37)"
                )
            n += 1
            found = probe(n)
        while n > 0:  # is the next smaller timebase still long enough? (no tolerance here)
            smaller = probe(n - 1)
            if smaller is None or smaller.interval_s < requested_s:
                break
            n, found = n - 1, smaller
        return n, found.interval_s, found.max_samples

    def single(self) -> None:
        """Arm one block capture with the conditions of the last `apply_capture` (PG §3.37)."""
        handle = self._open_handle()
        capture = self.capture
        if capture is None or self.timebase is None:
            raise RuntimeError("no capture applied; call apply_capture() first")
        self._forget_data()
        status, time_indisposed_ms = self._call(
            "ps2000aRunBlock",  # PG §3.37
            handle,
            capture.pre_samples,
            capture.post_samples,
            self.timebase,
            _OVERSAMPLE,
            _SEGMENT,
        )
        _check("ps2000aRunBlock", status)
        self.time_indisposed_ms = int(time_indisposed_ms)
        self._armed = True

    def wait_ready(self, timeout_s: float | None = None, poll_s: float = 0.01) -> None:
        """Poll `ps2000aIsReady` until the capture is done (PG §3.26).

        The deadline is `timeout_s` (default: the plug's) plus `time_indisposed_ms` of the last
        `single()`: PG §3.37 says the capture itself takes that long, without any auto-trigger
        wait. On expiry the capture is stopped (PG §3.65) and `TimeoutError` raised.
        """
        handle = self._open_handle()
        if not self._armed:
            raise RuntimeError("no capture armed; call single() first")
        limit = self._timeout_s if timeout_s is None else float(timeout_s)
        limit += self.time_indisposed_ms / 1000  # PG §3.37
        deadline = time.monotonic() + limit
        self.logger.debug("polling ps2000aIsReady (PG §3.26) for up to %g s", limit)
        polls = 0
        while True:
            polls += 1
            status, ready = self._api.ps2000aIsReady(handle)  # PG §3.26; logged once, not per poll
            _check("ps2000aIsReady", status)
            if ready != 0:  # PG §3.26: non-zero, ps2000aGetValues can be used
                self.logger.debug("ps2000aIsReady: ready after %d poll(s)", polls)
                self._ready = True
                return
            if time.monotonic() >= deadline:
                break
            time.sleep(poll_s)
        self.logger.debug("ps2000aIsReady: not ready after %d poll(s)", polls)
        self._forget_data()
        self._stopped = True
        try:
            (status,) = self._call("ps2000aStop", handle)  # PG §3.65: stops while waiting
            if not _is(status, _PICO_OK):
                self.logger.warning("ps2000aStop returned %s", status_name(status))
        except Exception:
            self.logger.warning("ps2000aStop failed", exc_info=True)
        raise TimeoutError(f"capture not ready within {limit:g} s")

    def read_waveform(self, ch: int) -> Waveform:
        """Waveform of channel `ch` of the finished capture.

        The first call after `single()` makes one `ps2000aGetValues` for all channels (PG §3.18);
        later calls reuse that data until the next `single()` or `apply_capture()`.
        """
        handle = self._open_handle()
        capture = self.capture
        if capture is None:
            raise RuntimeError("no capture applied; call apply_capture() first")
        if self._values is None:
            if not self._armed:
                if self._stopped:
                    raise RuntimeError(
                        "the capture was stopped before its data was read (PG §3.65: the data "
                        "is invalid after ps2000aStop); call single() to capture again"
                    )
                raise RuntimeError("no capture armed; call single() first")
            if not self._ready:
                raise RuntimeError("capture not finished; call wait_ready() first")
        channel = capture.channel(ch)  # ValueError if the channel is not enabled
        assert self.timebase is not None and self.sample_interval_s is not None
        if self._values is None:
            status, n_samples, overflow = self._call(
                "ps2000aGetValues",  # PG §3.18
                handle,
                0,
                capture.total_samples,
                _DOWNSAMPLE_RATIO,
                _RATIO_NONE,
                _SEGMENT,
            )
            _check("ps2000aGetValues", status)
            if n_samples < capture.total_samples:
                self.logger.warning(
                    "ps2000aGetValues returned %d of the %d requested samples",
                    n_samples,
                    capture.total_samples,
                )
            self._values = (int(n_samples), int(overflow))
        n_samples, overflow = self._values
        meta = WaveformMeta(
            channel=ch,
            range_v=channel.range,
            coupling=channel.coupling,
            max_adc=self.max_adc,
            sample_interval_s=self.sample_interval_s,
            pre_samples=capture.pre_samples,
            timebase=self.timebase,
            # PG §3.18: bit 0 = channel A. ASSUMPTION(hw) Q7: channel B..D are bits 1..3.
            overflow=bool((overflow >> (ch - 1)) & 1),
            serial=self.serial,
            variant=self.variant,
        )
        return waveform_from_raw(self._registered[ch][:n_samples].copy(), meta)

    def stop(self) -> None:
        """Stop the running capture (PG §3.65). Data already fetched stays readable."""
        handle = self._open_handle()
        # ASSUMPTION(hw): data already copied with ps2000aGetValues stays valid after
        # ps2000aStop, although PG §3.65 says "any data in the buffer will be invalid"
        # (open question 8).
        (status,) = self._call("ps2000aStop", handle)  # PG §3.65
        _check("ps2000aStop", status)
        self._stopped = self._armed and self._values is None  # armed, never fetched: data gone
        self._armed = False
        self._ready = False

    def ping(self) -> None:
        """Check the communication with the unit (PG §3.35)."""
        handle = self._open_handle()
        (status,) = self._call("ps2000aPingUnit", handle)  # PG §3.35
        _check("ps2000aPingUnit", status)

    def flash_led(self, count: int = 5) -> None:
        """Flash the front-panel LED `count` times (PG §3.5), to identify one of several scopes."""
        handle = self._open_handle()
        (status,) = self._call("ps2000aFlashLed", handle, count)  # PG §3.5
        _check("ps2000aFlashLed", status)

    def tearDown(self) -> None:
        """Stop any capture and close the handle this plug opened. Idempotent, never raises."""
        handle, self._handle = self._handle, None
        if handle is None:
            return
        self._forget_data()
        # PG §2.2 steps 7, 8: stop capturing, then close. Both are attempted whatever happens.
        steps: list[tuple[str, Callable[[int], tuple[int]]]] = [
            ("ps2000aStop", self._api.ps2000aStop),  # PG §3.65
            ("ps2000aCloseUnit", self._api.ps2000aCloseUnit),  # PG §3.2
        ]
        for name, step in steps:
            try:
                self.logger.debug("-> %s(%r)", name, handle)
                status = step(handle)[0]
                self.logger.debug("<- %s", status_name(status))
                if not _is(status, _PICO_OK):
                    self.logger.warning("%s returned %s", name, status_name(status))
            except Exception:
                self.logger.warning("%s failed", name, exc_info=True)
        self.logger.info("closed")
