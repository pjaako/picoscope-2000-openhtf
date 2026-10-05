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

# Declared at import; set values with ``CONF.load(...)`` only after importing this module.
CONF.declare(
    "picoscope_2000_serial",
    default_value=None,
    description="Serial number of the PicoScope to open (None: the first unit found)",
)
CONF.declare(
    "picoscope_2000_timeout_s",
    default_value=10.0,
    description="Default time in seconds wait_ready() waits for the capture to finish",
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
_SEGMENT = 0  # PG §3.29: one memory segment in phase 1
# ASSUMPTION(hw): 0 is a safe value for `oversample`, which the manual calls "not used"
# in §3.14 and §3.37 (open question 12).
_OVERSAMPLE = 0

_MAX_TIMEBASE_CALLS = 64  # SPEC §4 step 2: cap of the timebase search
_INTERVAL_REL_TOL = 1e-6  # SPEC §4 step 2: the driver returns a C float (PG §3.14)
_ALL_CHANNELS = (1, 2, 3, 4)  # PG §3.39: channels A..D


class PicoError(RuntimeError):
    """A driver call did not return `PICO_OK` (PG §4.1)."""

    def __init__(self, function: str, status: int, name: str, detail: str = "") -> None:
        message = f"{function} returned {name} (0x{status & 0xFFFFFFFF:08X})"
        if detail:
            message += f": {detail}"
        super().__init__(message)
        self.function = function
        self.status = status
        self.name = name


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
    # ASSUMPTION(hw): the trigger point is sample index pre_samples; PG §3.37 says the maximum
    # number returned is pre + post but not where the trigger sample sits (no matching item in
    # "Open questions", nearest is 15; reported to the owner).
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
    # ASSUMPTION(hw): the 2207B MSO is a 1 GS/s model; the search in apply_capture makes the
    # result correct either way (open question 1).
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
        self._buffers: dict[int, npt.NDArray[np.int16]] = {}
        self._armed = False
        self._ready = False
        self._values: tuple[int, int] | None = None  # (noOfSamples, overflow) of the last fetch

        status, count, serials = self._api.ps2000aEnumerateUnits()  # PG §3.4
        _check("ps2000aEnumerateUnits", status)
        self.logger.info("found %d unopened unit(s): %s", count, serials)
        if serial is None and count > 1:
            self.logger.warning(
                "no serial given and %d units found (%s); opening the first one. "
                "Set CONF.picoscope_2000_serial or pass serial=",
                count,
                serials,
            )

        status, handle = self._api.ps2000aOpenUnit(serial)  # PG §3.32
        _check("ps2000aOpenUnit", status)
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
                if _is(status, "PICO_INFO_UNAVAILABLE"):
                    self.info[name] = ""  # PG §3.17 Returns
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
            else:
                args = (name, 0, _DISABLED_COUPLING, _DISABLED_RANGE, _ANALOG_OFFSET)
            (status,) = self._call("ps2000aSetChannel", handle, *args)  # PG §3.39
            if _is(status, "PICO_INVALID_CHANNEL") and ch in (3, 4) and ch not in enabled:
                # ASSUMPTION(hw): disabling a channel the unit does not have gives
                # PICO_INVALID_CHANNEL, which means a two-channel unit (open question 21).
                self.logger.info("%s rejected as invalid: two-channel unit", name)
                self.channel_count = 2
                continue
            _check("ps2000aSetChannel", status)

        # Step 2: timebase search (PG §2.7, §3.14), step 3: the sample count must fit.
        total = capture.total_samples
        timebase, interval_s, max_samples = self._find_timebase(
            handle, total, capture.sample_interval
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

        # Step 5: one int16 buffer per enabled channel (PG §3.40). ASSUMPTION(hw): buffers
        # registered before ps2000aRunBlock survive until ps2000aGetValues (open question 18);
        # bufferLth counts samples (open question 19).
        buffers: dict[int, npt.NDArray[np.int16]] = {}
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
            buffers[ch] = buffer

        # Step 6: the resolved state.
        self.capture = capture
        self.timebase = timebase
        self.sample_interval_s = interval_s
        self.max_samples = max_samples
        self._buffers = buffers
        self.logger.info(
            "capture applied: channels %s, timebase %d (%g s per sample), %d samples",
            list(enabled),
            timebase,
            interval_s,
            total,
        )

    def _find_timebase(self, handle: int, total: int, requested_s: float) -> tuple[int, float, int]:
        """Smallest timebase whose interval is >= `requested_s`: (n, interval_s, maxSamples)."""
        calls = 0
        known: dict[int, _TimebaseResult | None] = {}  # None: the driver said "too small"

        def probe(n: int, *, tolerate_any: bool, tolerate_invalid: bool) -> _TimebaseResult | None:
            nonlocal calls
            if n in known:
                return known[n]
            if calls >= _MAX_TIMEBASE_CALLS:
                raise CaptureError(
                    f"no timebase for a sample interval of {requested_s:g} s found within "
                    f"{_MAX_TIMEBASE_CALLS} ps2000aGetTimebase2 calls"
                )
            calls += 1
            status, interval_ns, max_samples = self._call(
                "ps2000aGetTimebase2",  # PG §3.14
                handle,
                n,
                total,
                _OVERSAMPLE,
                _SEGMENT,
            )
            # ASSUMPTION(hw): on PICO_TOO_MANY_SAMPLES both outputs are filled in, so the
            # search can finish and the plug names both numbers (open question 26).
            if _is(status, _PICO_OK) or (_is(status, "PICO_TOO_MANY_SAMPLES") and max_samples > 0):
                known[n] = _TimebaseResult(interval_ns * ns, int(max_samples))
            elif tolerate_any or (tolerate_invalid and _is(status, "PICO_INVALID_TIMEBASE")):
                # ASSUMPTION(hw): an unavailable timebase (e.g. n = 0 with two channels, PG §2.7
                # footnote) is reported as PICO_INVALID_TIMEBASE (PG §3.14 Returns) and means
                # n is too small for the enabled channels (open questions 2 and 20).
                self.logger.info("timebase %d rejected: %s", n, status_name(status))
                known[n] = None
            else:
                raise PicoError("ps2000aGetTimebase2", status, status_name(status))
            return known[n]

        n = _estimate_timebase(requested_s)
        seen_valid = False
        first = True
        while True:  # up: from "too small" to the first interval >= requested
            candidate = probe(n, tolerate_any=first, tolerate_invalid=not seen_valid)
            first = False
            if candidate is not None:
                seen_valid = True
                if _at_least(candidate.interval_s, requested_s):
                    found = candidate
                    break
            n += 1
        while n > 0:  # down: is the next smaller timebase still long enough?
            smaller = probe(n - 1, tolerate_any=False, tolerate_invalid=True)
            if smaller is None or not _at_least(smaller.interval_s, requested_s):
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

        On expiry of the deadline the capture is stopped (PG §3.65) and `TimeoutError` raised.
        """
        handle = self._open_handle()
        if not self._armed:
            raise RuntimeError("no capture armed; call single() first")
        limit = self._timeout_s if timeout_s is None else float(timeout_s)
        deadline = time.monotonic() + limit
        while True:
            status, ready = self._call("ps2000aIsReady", handle)  # PG §3.26
            _check("ps2000aIsReady", status)
            if ready != 0:  # PG §3.26: non-zero, ps2000aGetValues can be used
                self._ready = True
                return
            if time.monotonic() >= deadline:
                break
            time.sleep(poll_s)
        self._forget_data()
        try:
            (status,) = self._call("ps2000aStop", handle)  # PG §3.65: stops while waiting
            if not _is(status, _PICO_OK):
                self.logger.warning("ps2000aStop returned %s", status_name(status))
        except Exception:
            self.logger.warning("ps2000aStop failed", exc_info=True)
        raise TimeoutError(f"no trigger within {limit:g} s")

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
                1,
                _RATIO_NONE,
                _SEGMENT,
            )
            _check("ps2000aGetValues", status)
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
            overflow=bool((overflow >> (ch - 1)) & 1),  # PG §3.18: bit 0 = channel A
            serial=self.serial,
            variant=self.variant,
        )
        return waveform_from_raw(self._buffers[ch][:n_samples].copy(), meta)

    def stop(self) -> None:
        """Stop the running capture (PG §3.65). Data already fetched stays readable."""
        handle = self._open_handle()
        # ASSUMPTION(hw): data already copied with ps2000aGetValues stays valid after
        # ps2000aStop, although PG §3.65 says "any data in the buffer will be invalid"
        # (open question 8).
        (status,) = self._call("ps2000aStop", handle)  # PG §3.65
        _check("ps2000aStop", status)
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
