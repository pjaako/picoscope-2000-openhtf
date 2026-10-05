"""The driver seam: `Ps2000aApi` (Protocol) and `PicosdkApi` (the real ctypes adapter).

The Protocol has one method per manual function used, named exactly like the C function, with
arguments in the manual's order. `in` arguments are parameters, `out` arguments are returned, the
`PICO_STATUS` code is always the first element of the returned tuple. Enum arguments are the
manual's enum member names as strings; `PicosdkApi` resolves them to integers through the enum
dicts picosdk declares on its library object. Numeric enum values and status codes are not in the
manual (PG §4.1, §4.2); picosdk mirrors `PicoStatus.h` / `ps2000aApi.h`.

`picosdk.ps2000a` raises at import time when the native library is missing, so it is imported
lazily, on the first driver call of a `PicosdkApi` built without an injected library, and never at
module import. `picosdk.constants` imports without the native library and is imported here.

"PG" = PicoScope 2000 Series (A API) Programmer's Guide, ps2000apg.en-12.
"""

from __future__ import annotations

from ctypes import POINTER, byref, c_float, c_int16, c_int32, c_uint32, create_string_buffer
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt
from picosdk.constants import PICO_STATUS, PICO_STATUS_LOOKUP  # PG §4.1 (PicoStatus.h mirror)

__all__ = ["Ps2000aApi", "PicosdkApi", "status_code", "status_name"]

_UNIT_INFO_BUFFER = 256  # bytes for ps2000aGetUnitInfo; the manual gives no size, PG §3.17
_SERIALS_BUFFER = 1024  # bytes for ps2000aEnumerateUnits; the manual gives no size, PG §3.4


def status_name(code: int) -> str:
    """Name of a `PICO_STATUS` code (PG §4.1), or `0xHHHHHHHH` when picosdk does not know it."""
    name: str | None = PICO_STATUS_LOOKUP.get(code)
    if name is not None:
        return name
    return f"0x{code & 0xFFFFFFFF:08X}"


def status_code(name: str) -> int:
    """Value of a `PICO_STATUS` name (PG §4.1); `KeyError` for an unknown name."""
    return int(PICO_STATUS[name])


class Ps2000aApi(Protocol):
    """The seam between the plug and the driver; implemented by `PicosdkApi` and by the fake."""

    def ps2000aEnumerateUnits(self) -> tuple[int, int, str]: ...  # status, count, serials  PG §3.4

    def ps2000aOpenUnit(
        self, serial: str | None
    ) -> tuple[int, int]: ...  # status, handle          PG §3.32

    def ps2000aCloseUnit(self, handle: int) -> tuple[int]: ...  # PG §3.2

    def ps2000aGetUnitInfo(
        self, handle: int, info: str
    ) -> tuple[int, str]: ...  # info = "PICO_VARIANT_INFO" etc.  PG §3.17

    def ps2000aPingUnit(self, handle: int) -> tuple[int]: ...  # PG §3.35

    def ps2000aFlashLed(self, handle: int, start: int) -> tuple[int]: ...  # PG §3.5

    def ps2000aMaximumValue(self, handle: int) -> tuple[int, int]: ...  # PG §3.28

    def ps2000aMinimumValue(self, handle: int) -> tuple[int, int]: ...  # PG §3.30

    def ps2000aSetChannel(
        self, handle: int, channel: str, enabled: int, type: str, range: str, analogOffset: float
    ) -> tuple[int]: ...  # PG §3.39

    def ps2000aGetTimebase2(
        self, handle: int, timebase: int, noSamples: int, oversample: int, segmentIndex: int
    ) -> tuple[int, float, int]: ...  # status, timeIntervalNanoseconds, maxSamples  PG §3.14

    def ps2000aSetSimpleTrigger(
        self,
        handle: int,
        enable: int,
        source: str,
        threshold: int,
        direction: str,
        delay: int,
        autoTrigger_ms: int,
    ) -> tuple[int]: ...  # PG §3.56

    def ps2000aSetDataBuffer(
        self, handle: int, channel: str, buffer: npt.NDArray[np.int16], segmentIndex: int, mode: str
    ) -> tuple[int]: ...  # bufferLth = len(buffer)  PG §3.40

    def ps2000aRunBlock(
        self,
        handle: int,
        noOfPreTriggerSamples: int,
        noOfPostTriggerSamples: int,
        timebase: int,
        oversample: int,
        segmentIndex: int,
    ) -> tuple[int, int]: ...  # status, timeIndisposedMs; lpReady/pParameter always NULL  PG §3.37

    def ps2000aIsReady(self, handle: int) -> tuple[int, int]: ...  # status, ready  PG §3.26

    def ps2000aGetValues(
        self,
        handle: int,
        startIndex: int,
        noOfSamples: int,
        downSampleRatio: int,
        downSampleRatioMode: str,
        segmentIndex: int,
    ) -> tuple[int, int, int]: ...  # status, noOfSamples out, overflow  PG §3.18

    def ps2000aStop(self, handle: int) -> tuple[int]: ...  # PG §3.65

    def ps2000aMemorySegments(
        self, handle: int, nSegments: int
    ) -> tuple[int, int]: ...  # status, nMaxSamples (all channels)  PG §3.29


def _checked(value: int, lo: int, hi: int, what: str) -> int:
    """Return `value` if it fits the C type's range, else `ValueError` (ctypes would wrap)."""
    if isinstance(value, bool) or not isinstance(value, int | np.integer):
        raise ValueError(f"{what} must be an integer, got {value!r}")
    if not lo <= value <= hi:
        raise ValueError(f"{what} {value} is outside {lo}..{hi}")
    return int(value)


def _i16(value: int, what: str) -> int:
    return _checked(value, -(2**15), 2**15 - 1, what)  # int16_t, PG §4.3


def _i32(value: int, what: str) -> int:
    return _checked(value, -(2**31), 2**31 - 1, what)  # int32_t, PG §4.3


def _u32(value: int, what: str) -> int:
    return _checked(value, 0, 2**32 - 1, what)  # uint32_t, PG §4.3


class PicosdkApi(Ps2000aApi):
    """`Ps2000aApi` on top of picosdk's ctypes wrapper of the native ps2000a library.

    `PicosdkApi()` imports `picosdk.ps2000a` on the first driver call, not in the constructor, so
    the object can be built (and the package imported) on a machine without the native driver; the
    import error (`picosdk.errors.CannotFindPicoSDKError`) propagates with its own message.
    `PicosdkApi(lib=...)` uses the given object instead (tests) and imports nothing from picosdk.

    Methods marshal the arguments as the manual prototype requires, resolve enum names through the
    enum dicts on the library object (unknown name: `ValueError` before any driver call) and return
    the status first, then the out arguments. No status interpretation, no retries, no sleeps.
    The data buffer given to `ps2000aSetDataBuffer` must stay alive (and unmoved) until the last
    `ps2000aGetValues` that fills it; the driver keeps the raw pointer.
    """

    def __init__(self, lib: object | None = None) -> None:
        self._lib: Any = lib

    def _library(self) -> Any:
        if self._lib is None:
            from picosdk.ps2000a import ps2000a  # lazy: raises without the native library

            self._lib = ps2000a
        return self._lib

    def _fn(self, name: str) -> Any:
        return getattr(self._library(), name)

    def _enum(self, table: str, name: str) -> int:
        """Resolve an enum member name through the dict picosdk keeps on the library object."""
        library = self._library()
        try:
            members = getattr(library, table)
        except AttributeError:
            raise ValueError(
                f"the library has no enum table {table} (looking up {name!r})"
            ) from None
        try:
            return int(members[name])
        except (KeyError, TypeError):
            raise ValueError(f"unknown {table} member {name!r}") from None

    def ps2000aEnumerateUnits(self) -> tuple[int, int, str]:  # PG §3.4
        fn = self._fn("ps2000aEnumerateUnits")
        count = c_int16(0)
        serials = create_string_buffer(_SERIALS_BUFFER)
        serial_lth = c_int16(_SERIALS_BUFFER)  # in: buffer length, out: string length
        status = fn(byref(count), serials, byref(serial_lth))
        return int(status), int(count.value), serials.value.decode("ascii", errors="replace")

    def ps2000aOpenUnit(self, serial: str | None) -> tuple[int, int]:  # PG §3.32
        fn = self._fn("ps2000aOpenUnit")
        serial_arg = None if serial is None else serial.encode("ascii")  # NULL: first unit found
        handle = c_int16(0)
        status = fn(byref(handle), serial_arg)
        return int(status), int(handle.value)

    def ps2000aCloseUnit(self, handle: int) -> tuple[int]:  # PG §3.2
        fn = self._fn("ps2000aCloseUnit")
        return (int(fn(c_int16(_i16(handle, "handle")))),)

    def ps2000aGetUnitInfo(self, handle: int, info: str) -> tuple[int, str]:  # PG §3.17
        info_code = self._enum("PICO_INFO", info)  # PG §3.17 info table, codes 0..10
        fn = self._fn("ps2000aGetUnitInfo")
        string = create_string_buffer(_UNIT_INFO_BUFFER)
        required = c_int16(0)
        status = fn(
            c_int16(_i16(handle, "handle")),
            string,
            c_int16(_UNIT_INFO_BUFFER),
            byref(required),
            c_uint32(info_code),
        )
        text = string.raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")
        return int(status), text

    def ps2000aPingUnit(self, handle: int) -> tuple[int]:  # PG §3.35
        fn = self._fn("ps2000aPingUnit")
        return (int(fn(c_int16(_i16(handle, "handle")))),)

    def ps2000aFlashLed(self, handle: int, start: int) -> tuple[int]:  # PG §3.5
        fn = self._fn("ps2000aFlashLed")
        return (int(fn(c_int16(_i16(handle, "handle")), c_int16(_i16(start, "start")))),)

    def ps2000aMaximumValue(self, handle: int) -> tuple[int, int]:  # PG §3.28
        fn = self._fn("ps2000aMaximumValue")
        value = c_int16(0)
        status = fn(c_int16(_i16(handle, "handle")), byref(value))
        return int(status), int(value.value)

    def ps2000aMinimumValue(self, handle: int) -> tuple[int, int]:  # PG §3.30
        fn = self._fn("ps2000aMinimumValue")
        value = c_int16(0)
        status = fn(c_int16(_i16(handle, "handle")), byref(value))
        return int(status), int(value.value)

    def ps2000aSetChannel(
        self, handle: int, channel: str, enabled: int, type: str, range: str, analogOffset: float
    ) -> tuple[int]:  # PG §3.39
        channel_code = self._enum("PS2000A_CHANNEL", channel)
        coupling_code = self._enum("PS2000A_COUPLING", type)
        range_code = self._enum("PS2000A_RANGE", range)
        fn = self._fn("ps2000aSetChannel")
        status = fn(
            c_int16(_i16(handle, "handle")),
            c_int32(channel_code),
            c_int16(_i16(enabled, "enabled")),
            c_int32(coupling_code),
            c_int32(range_code),
            c_float(analogOffset),
        )
        return (int(status),)

    def ps2000aGetTimebase2(
        self, handle: int, timebase: int, noSamples: int, oversample: int, segmentIndex: int
    ) -> tuple[int, float, int]:  # PG §3.14
        fn = self._fn("ps2000aGetTimebase2")
        interval_ns = c_float(0.0)
        max_samples = c_int32(0)
        status = fn(
            c_int16(_i16(handle, "handle")),
            c_uint32(_u32(timebase, "timebase")),
            c_int32(_i32(noSamples, "noSamples")),
            byref(interval_ns),
            c_int16(_i16(oversample, "oversample")),
            byref(max_samples),
            c_uint32(_u32(segmentIndex, "segmentIndex")),
        )
        return int(status), float(interval_ns.value), int(max_samples.value)

    def ps2000aSetSimpleTrigger(
        self,
        handle: int,
        enable: int,
        source: str,
        threshold: int,
        direction: str,
        delay: int,
        autoTrigger_ms: int,
    ) -> tuple[int]:  # PG §3.56
        source_code = self._enum("PS2000A_CHANNEL", source)
        direction_code = self._enum("PS2000A_THRESHOLD_DIRECTION", direction)  # PG §3.56, §3.58
        fn = self._fn("ps2000aSetSimpleTrigger")
        status = fn(
            c_int16(_i16(handle, "handle")),
            c_int16(_i16(enable, "enable")),
            c_int32(source_code),
            c_int16(_i16(threshold, "threshold")),
            c_int32(direction_code),
            c_uint32(_u32(delay, "delay")),
            c_int16(_i16(autoTrigger_ms, "autoTrigger_ms")),
        )
        return (int(status),)

    def ps2000aSetDataBuffer(
        self, handle: int, channel: str, buffer: npt.NDArray[np.int16], segmentIndex: int, mode: str
    ) -> tuple[int]:  # PG §3.40
        channel_code = self._enum("PS2000A_CHANNEL", channel)
        mode_code = self._enum("PS2000A_RATIO_MODE", mode)  # PG §3.18.1
        if not isinstance(buffer, np.ndarray):
            raise ValueError("buffer must be a numpy array")
        if buffer.dtype != np.int16:
            raise ValueError(f"buffer must have dtype int16, got {buffer.dtype}")
        if buffer.ndim != 1 or not buffer.flags.c_contiguous:
            raise ValueError("buffer must be a one-dimensional C-contiguous array")
        fn = self._fn("ps2000aSetDataBuffer")
        status = fn(
            c_int16(_i16(handle, "handle")),
            c_int32(channel_code),
            buffer.ctypes.data_as(POINTER(c_int16)),
            c_int32(_i32(len(buffer), "bufferLth")),  # ASSUMPTION(hw): bufferLth counts samples
            c_uint32(_u32(segmentIndex, "segmentIndex")),
            c_int32(mode_code),
        )
        return (int(status),)

    def ps2000aRunBlock(
        self,
        handle: int,
        noOfPreTriggerSamples: int,
        noOfPostTriggerSamples: int,
        timebase: int,
        oversample: int,
        segmentIndex: int,
    ) -> tuple[int, int]:  # PG §3.37
        fn = self._fn("ps2000aRunBlock")
        time_indisposed_ms = c_int32(0)
        status = fn(
            c_int16(_i16(handle, "handle")),
            c_int32(_i32(noOfPreTriggerSamples, "noOfPreTriggerSamples")),
            c_int32(_i32(noOfPostTriggerSamples, "noOfPostTriggerSamples")),
            c_uint32(_u32(timebase, "timebase")),
            c_int16(_i16(oversample, "oversample")),
            byref(time_indisposed_ms),
            c_uint32(_u32(segmentIndex, "segmentIndex")),
            None,  # lpReady: NULL, poll with ps2000aIsReady (PG §3.37)
            None,  # pParameter: unused without a callback
        )
        return int(status), int(time_indisposed_ms.value)

    def ps2000aIsReady(self, handle: int) -> tuple[int, int]:  # PG §3.26
        fn = self._fn("ps2000aIsReady")
        ready = c_int16(0)
        status = fn(c_int16(_i16(handle, "handle")), byref(ready))
        return int(status), int(ready.value)

    def ps2000aGetValues(
        self,
        handle: int,
        startIndex: int,
        noOfSamples: int,
        downSampleRatio: int,
        downSampleRatioMode: str,
        segmentIndex: int,
    ) -> tuple[int, int, int]:  # PG §3.18
        mode_code = self._enum("PS2000A_RATIO_MODE", downSampleRatioMode)  # PG §3.18.1
        fn = self._fn("ps2000aGetValues")
        n_samples = c_uint32(_u32(noOfSamples, "noOfSamples"))  # in: requested, out: retrieved
        overflow = c_int16(0)
        status = fn(
            c_int16(_i16(handle, "handle")),
            c_uint32(_u32(startIndex, "startIndex")),
            byref(n_samples),
            c_uint32(_u32(downSampleRatio, "downSampleRatio")),
            c_int32(mode_code),
            c_uint32(_u32(segmentIndex, "segmentIndex")),
            byref(overflow),
        )
        # overflow is a bit field, bit 0 = channel A (PG §3.18); report it as unsigned 16 bits
        return int(status), int(n_samples.value), int(overflow.value) & 0xFFFF

    def ps2000aStop(self, handle: int) -> tuple[int]:  # PG §3.65
        fn = self._fn("ps2000aStop")
        return (int(fn(c_int16(_i16(handle, "handle")))),)

    def ps2000aMemorySegments(self, handle: int, nSegments: int) -> tuple[int, int]:  # PG §3.29
        fn = self._fn("ps2000aMemorySegments")
        n_max_samples = c_int32(0)  # out: samples per segment, summed over all channels
        status = fn(
            c_int16(_i16(handle, "handle")),
            c_uint32(_u32(nSegments, "nSegments")),
            byref(n_max_samples),
        )
        return int(status), int(n_max_samples.value)
