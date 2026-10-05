"""Tests for `driver.py`: ctypes marshaling of `PicosdkApi` against a stub library object.

`_StubLib` stands in for picosdk's `ps2000a` library object: it carries the enum dicts (values
copied from the `picosdk enums` lines of docs/api_reference.md; they are picosdk's values, not the
manual's) and one stub callable per driver function. Each stub records the ctypes arguments it
receives (type and value, before it writes anything) and writes the out parameters.
"""

import ctypes
import re
import subprocess
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from picoscope_2000_openhtf import (
    Capture,
    Channel,
    Edge,
    PicoError,
    PicoScope2000Plug,
    driver,
)
from picoscope_2000_openhtf import plug as plug_module
from picoscope_2000_openhtf.driver import PicosdkApi, status_code, status_name
from picoscope_2000_openhtf.units import V, us

c_int16, c_int32, c_uint32, c_float = (
    ctypes.c_int16,
    ctypes.c_int32,
    ctypes.c_uint32,
    ctypes.c_float,
)


def _describe(arg: Any) -> Any:
    """Type and value of one argument as the C function would receive it."""
    if arg is None:
        return None
    if type(arg).__name__ == "CArgObject":  # result of ctypes.byref()
        return ("byref", type(arg._obj), arg._obj.value)
    if isinstance(arg, bytes):  # passed straight to a c_char_p parameter
        return ("bytes", arg)
    if isinstance(arg, ctypes.Array):
        return (type(arg), len(arg))
    if isinstance(arg, ctypes._Pointer):
        return (type(arg), ctypes.cast(arg, ctypes.c_void_p).value)
    if isinstance(arg, ctypes._SimpleCData):
        return (type(arg), arg.value)
    return ("other", type(arg))


def _out(arg: Any, value: Any) -> None:
    """Write into the object behind a `byref()` argument."""
    arg._obj.value = value


class _StubLib:
    """Library object with the picosdk enum dicts and recording stub functions."""

    # picosdk enums, docs/api_reference.md "picosdk enums" lines (§3.39, §3.56, §3.18)
    PS2000A_CHANNEL = {
        "PS2000A_CHANNEL_A": 0,
        "PS2000A_CHANNEL_B": 1,
        "PS2000A_CHANNEL_C": 2,
        "PS2000A_CHANNEL_D": 3,
        "PS2000A_EXTERNAL": 4,
        "PS2000A_MAX_CHANNELS": 4,
        "PS2000A_TRIGGER_AUX": 5,
        "PS2000A_MAX_TRIGGER_SOURCE": 6,
    }
    PS2000A_COUPLING = {"PS2000A_AC": 0, "PS2000A_DC": 1}
    PS2000A_RANGE = {
        "PS2000A_10MV": 0,
        "PS2000A_20MV": 1,
        "PS2000A_50MV": 2,
        "PS2000A_100MV": 3,
        "PS2000A_200MV": 4,
        "PS2000A_500MV": 5,
        "PS2000A_1V": 6,
        "PS2000A_2V": 7,
        "PS2000A_5V": 8,
        "PS2000A_10V": 9,
        "PS2000A_20V": 10,
        "PS2000A_50V": 11,
        "PS2000A_MAX_RANGES": 12,
    }
    PS2000A_THRESHOLD_DIRECTION = {
        "PS2000A_ABOVE": 0,
        "PS2000A_BELOW": 1,
        "PS2000A_RISING": 2,
        "PS2000A_FALLING": 3,
        "PS2000A_RISING_OR_FALLING": 4,
        "PS2000A_ABOVE_LOWER": 5,
        "PS2000A_BELOW_LOWER": 6,
        "PS2000A_RISING_LOWER": 7,
        "PS2000A_FALLING_LOWER": 8,
        "PS2000A_INSIDE": 0,
        "PS2000A_OUTSIDE": 1,
        "PS2000A_ENTER": 2,
        "PS2000A_EXIT": 3,
        "PS2000A_ENTER_OR_EXIT": 4,
        "PS2000A_NONE": 2,
        "PS2000A_POSITIVE_RUNT": 9,
        "PS2000A_NEGATIVE_RUNT": 10,
    }
    PS2000A_RATIO_MODE = {
        "PS2000A_RATIO_MODE_NONE": 0,
        "PS2000A_RATIO_MODE_AGGREGATE": 1,
        "PS2000A_RATIO_MODE_DECIMATE": 2,
        "PS2000A_RATIO_MODE_AVERAGE": 4,
    }
    # PG §3.17 info table, codes 0..10 (picosdk.constants.PICO_INFO)
    PICO_INFO = {
        "PICO_DRIVER_VERSION": 0,
        "PICO_USB_VERSION": 1,
        "PICO_HARDWARE_VERSION": 2,
        "PICO_VARIANT_INFO": 3,
        "PICO_BATCH_AND_SERIAL": 4,
        "PICO_CAL_DATE": 5,
        "PICO_KERNEL_VERSION": 6,
        "PICO_DIGITAL_HARDWARE_VERSION": 7,
        "PICO_ANALOGUE_HARDWARE_VERSION": 8,
        "PICO_FIRMWARE_VERSION_1": 9,
        "PICO_FIRMWARE_VERSION_2": 10,
    }

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []  # (name, described args)
        self.raw: dict[str, tuple[Any, ...]] = {}  # name -> the actual argument objects
        self.status = 0  # status every stub returns

    def _record(self, name: str, args: tuple[Any, ...]) -> tuple[Any, ...]:
        self.calls.append((name, tuple(_describe(a) for a in args)))
        self.raw[name] = args
        return tuple(_describe(a) for a in args)

    def ps2000aEnumerateUnits(self, count: Any, serials: Any, serial_lth: Any) -> int:
        self._record("ps2000aEnumerateUnits", (count, serials, serial_lth))
        _out(count, 2)
        serials.value = b"FAKE0/001,FAKE0/002"
        _out(serial_lth, 19)
        return self.status

    def ps2000aOpenUnit(self, handle: Any, serial: Any) -> int:
        self._record("ps2000aOpenUnit", (handle, serial))
        _out(handle, 1)
        return self.status

    def ps2000aCloseUnit(self, handle: Any) -> int:
        self._record("ps2000aCloseUnit", (handle,))
        return self.status

    def ps2000aGetUnitInfo(
        self, handle: Any, string: Any, string_length: Any, required_size: Any, info: Any
    ) -> int:
        self._record("ps2000aGetUnitInfo", (handle, string, string_length, required_size, info))
        string.value = b"2207BMSO"
        _out(required_size, 9)
        return self.status

    def ps2000aPingUnit(self, handle: Any) -> int:
        self._record("ps2000aPingUnit", (handle,))
        return self.status

    def ps2000aFlashLed(self, handle: Any, start: Any) -> int:
        self._record("ps2000aFlashLed", (handle, start))
        return self.status

    def ps2000aMaximumValue(self, handle: Any, value: Any) -> int:
        self._record("ps2000aMaximumValue", (handle, value))
        _out(value, 32512)
        return self.status

    def ps2000aMinimumValue(self, handle: Any, value: Any) -> int:
        self._record("ps2000aMinimumValue", (handle, value))
        _out(value, -32512)
        return self.status

    def ps2000aSetChannel(self, *args: Any) -> int:
        self._record("ps2000aSetChannel", args)
        return self.status

    def ps2000aGetTimebase2(self, *args: Any) -> int:
        self._record("ps2000aGetTimebase2", args)
        _out(args[3], 8.0)
        _out(args[5], 1000)
        return self.status

    def ps2000aSetSimpleTrigger(self, *args: Any) -> int:
        self._record("ps2000aSetSimpleTrigger", args)
        return self.status

    def ps2000aSetDataBuffer(self, *args: Any) -> int:
        self._record("ps2000aSetDataBuffer", args)
        return self.status

    def ps2000aRunBlock(self, *args: Any) -> int:
        self._record("ps2000aRunBlock", args)
        _out(args[5], 3)
        return self.status

    def ps2000aIsReady(self, handle: Any, ready: Any) -> int:
        self._record("ps2000aIsReady", (handle, ready))
        _out(ready, 1)
        return self.status

    def ps2000aGetValues(self, *args: Any) -> int:
        self._record("ps2000aGetValues", args)
        _out(args[2], 1900)  # noOfSamples out: fewer than requested
        _out(args[6], 0b10)  # overflow: channel B
        return self.status

    def ps2000aStop(self, handle: Any) -> int:
        self._record("ps2000aStop", (handle,))
        return self.status

    def ps2000aMemorySegments(self, handle: Any, n_segments: Any, n_max_samples: Any) -> int:
        self._record("ps2000aMemorySegments", (handle, n_segments, n_max_samples))
        _out(n_max_samples, 64000)
        return self.status


@pytest.fixture
def stub() -> _StubLib:
    return _StubLib()


@pytest.fixture
def api(stub: _StubLib) -> PicosdkApi:
    return PicosdkApi(lib=stub)


def _byref(ctype: type, value: Any) -> tuple[str, type, Any]:
    return ("byref", ctype, value)


# --- per-function marshaling, in manual argument order ----------------------------------------


def test_open_unit_first_unit(api: PicosdkApi, stub: _StubLib) -> None:
    assert api.ps2000aOpenUnit(None) == (0, 1)  # PG §3.32
    assert stub.calls == [("ps2000aOpenUnit", (_byref(c_int16, 0), None))]


def test_open_unit_by_serial(api: PicosdkApi, stub: _StubLib) -> None:
    assert api.ps2000aOpenUnit("FAKE0/001") == (0, 1)
    assert stub.calls == [("ps2000aOpenUnit", (_byref(c_int16, 0), ("bytes", b"FAKE0/001")))]


def test_enumerate_units(api: PicosdkApi, stub: _StubLib) -> None:
    assert api.ps2000aEnumerateUnits() == (0, 2, "FAKE0/001,FAKE0/002")  # PG §3.4
    ((name, args),) = stub.calls
    assert name == "ps2000aEnumerateUnits" and len(args) == 3
    assert args[0] == _byref(c_int16, 0)
    assert args[1] == (ctypes.c_char * 1024, 1024)
    assert args[2] == _byref(c_int16, 1024)  # serialLth in: buffer length


def test_close_unit(api: PicosdkApi, stub: _StubLib) -> None:
    assert api.ps2000aCloseUnit(1) == (0,)  # PG §3.2
    assert stub.calls == [("ps2000aCloseUnit", ((c_int16, 1),))]


def test_get_unit_info(api: PicosdkApi, stub: _StubLib) -> None:
    assert api.ps2000aGetUnitInfo(1, "PICO_VARIANT_INFO") == (0, "2207BMSO")  # PG §3.17
    ((name, args),) = stub.calls
    assert name == "ps2000aGetUnitInfo" and len(args) == 5
    assert args[0] == (c_int16, 1)
    assert args[1] == (ctypes.c_char * 256, 256)
    assert args[2] == (c_int16, 256)
    assert args[3] == _byref(c_int16, 0)
    assert args[4] == (c_uint32, 3)  # PICO_VARIANT_INFO


def test_get_unit_info_strips_terminator_and_garbage_after_it(
    api: PicosdkApi, stub: _StubLib
) -> None:
    def write(handle: Any, string: Any, *rest: Any) -> int:
        string.raw = b"KJL87/006\x00junk".ljust(256, b"\x00")
        return 0

    stub.ps2000aGetUnitInfo = write  # type: ignore[method-assign,assignment]
    assert api.ps2000aGetUnitInfo(1, "PICO_BATCH_AND_SERIAL") == (0, "KJL87/006")


def test_get_unit_info_all_codes(api: PicosdkApi, stub: _StubLib) -> None:
    for code, name in enumerate(_StubLib.PICO_INFO):  # PG §3.17: codes 0..10
        stub.calls.clear()
        api.ps2000aGetUnitInfo(1, name)
        assert stub.calls[0][1][4] == (c_uint32, code)


def test_ping_and_flash_led(api: PicosdkApi, stub: _StubLib) -> None:
    assert api.ps2000aPingUnit(1) == (0,)  # PG §3.35
    assert api.ps2000aFlashLed(1, 5) == (0,)  # PG §3.5
    assert api.ps2000aFlashLed(1, -1) == (0,)  # negative: flash indefinitely
    assert stub.calls == [
        ("ps2000aPingUnit", ((c_int16, 1),)),
        ("ps2000aFlashLed", ((c_int16, 1), (c_int16, 5))),
        ("ps2000aFlashLed", ((c_int16, 1), (c_int16, -1))),
    ]


def test_maximum_and_minimum_value(api: PicosdkApi, stub: _StubLib) -> None:
    assert api.ps2000aMaximumValue(1) == (0, 32512)  # PG §3.28
    assert api.ps2000aMinimumValue(1) == (0, -32512)  # PG §3.30
    assert stub.calls == [
        ("ps2000aMaximumValue", ((c_int16, 1), _byref(c_int16, 0))),
        ("ps2000aMinimumValue", ((c_int16, 1), _byref(c_int16, 0))),
    ]


def test_set_channel(api: PicosdkApi, stub: _StubLib) -> None:
    result = api.ps2000aSetChannel(1, "PS2000A_CHANNEL_B", 1, "PS2000A_DC", "PS2000A_2V", 0.0)
    assert result == (0,)  # PG §3.39
    assert stub.calls == [
        (
            "ps2000aSetChannel",
            (
                (c_int16, 1),  # handle
                (c_int32, 1),  # channel B
                (c_int16, 1),  # enabled
                (c_int32, 1),  # PS2000A_DC
                (c_int32, 7),  # PS2000A_2V
                (c_float, 0.0),  # analogOffset
            ),
        )
    ]


def test_set_channel_disabled_ac_20v(api: PicosdkApi, stub: _StubLib) -> None:
    api.ps2000aSetChannel(2, "PS2000A_CHANNEL_D", 0, "PS2000A_AC", "PS2000A_20V", 0.5)
    assert stub.calls[0][1] == (
        (c_int16, 2),
        (c_int32, 3),
        (c_int16, 0),
        (c_int32, 0),
        (c_int32, 10),
        (c_float, 0.5),
    )


def test_get_timebase2(api: PicosdkApi, stub: _StubLib) -> None:
    assert api.ps2000aGetTimebase2(1, 5, 2000, 0, 0) == (0, 8.0, 1000)  # PG §3.14
    assert stub.calls == [
        (
            "ps2000aGetTimebase2",
            (
                (c_int16, 1),  # handle
                (c_uint32, 5),  # timebase
                (c_int32, 2000),  # noSamples
                _byref(c_float, 0.0),  # timeIntervalNanoseconds
                (c_int16, 0),  # oversample
                _byref(c_int32, 0),  # maxSamples
                (c_uint32, 0),  # segmentIndex
            ),
        )
    ]


def test_set_simple_trigger(api: PicosdkApi, stub: _StubLib) -> None:
    result = api.ps2000aSetSimpleTrigger(
        1, 1, "PS2000A_CHANNEL_A", -8128, "PS2000A_FALLING", 100, 1000
    )
    assert result == (0,)  # PG §3.56
    assert stub.calls == [
        (
            "ps2000aSetSimpleTrigger",
            (
                (c_int16, 1),  # handle
                (c_int16, 1),  # enable
                (c_int32, 0),  # source A
                (c_int16, -8128),  # threshold (ADC counts)
                (c_int32, 3),  # PS2000A_FALLING
                (c_uint32, 100),  # delay
                (c_int16, 1000),  # autoTrigger_ms
            ),
        )
    ]


def test_set_simple_trigger_disabled(api: PicosdkApi, stub: _StubLib) -> None:
    api.ps2000aSetSimpleTrigger(1, 0, "PS2000A_CHANNEL_A", 0, "PS2000A_RISING", 0, 0)
    assert stub.calls[0][1] == (
        (c_int16, 1),
        (c_int16, 0),
        (c_int32, 0),
        (c_int16, 0),
        (c_int32, 2),
        (c_uint32, 0),
        (c_int16, 0),
    )


def test_set_data_buffer(api: PicosdkApi, stub: _StubLib) -> None:
    buf = np.zeros(2000, dtype=np.int16)
    result = api.ps2000aSetDataBuffer(1, "PS2000A_CHANNEL_B", buf, 0, "PS2000A_RATIO_MODE_NONE")
    assert result == (0,)  # PG §3.40
    ((name, args),) = stub.calls
    assert name == "ps2000aSetDataBuffer" and len(args) == 6
    assert args[0] == (c_int16, 1)
    assert args[1] == (c_int32, 1)
    assert args[2] == (ctypes.POINTER(c_int16), buf.ctypes.data)  # the buffer's own address
    assert args[3] == (c_int32, 2000)  # bufferLth = len(buffer)
    assert args[4] == (c_uint32, 0)
    assert args[5] == (c_int32, 0)  # PS2000A_RATIO_MODE_NONE


def test_set_data_buffer_pointer_writes_into_the_numpy_array(
    api: PicosdkApi, stub: _StubLib
) -> None:
    buf = np.zeros(4, dtype=np.int16)
    api.ps2000aSetDataBuffer(1, "PS2000A_CHANNEL_A", buf, 0, "PS2000A_RATIO_MODE_NONE")
    pointer = stub.raw["ps2000aSetDataBuffer"][2]
    pointer[2] = 1234  # what the driver does through the pointer
    assert buf[2] == 1234


@pytest.mark.parametrize(
    "make",
    [
        pytest.param(lambda: np.zeros(8, dtype=np.int16)[::2], id="strided"),
        pytest.param(lambda: np.zeros(4, dtype=np.int32), id="int32"),
        pytest.param(lambda: np.zeros(4, dtype=np.float64), id="float64"),
        pytest.param(lambda: np.zeros((2, 2), dtype=np.int16), id="2d"),
        pytest.param(lambda: [0, 0, 0], id="list"),
    ],
)
def test_set_data_buffer_rejects_bad_buffers(
    api: PicosdkApi, stub: _StubLib, make: Callable[[], Any]
) -> None:
    with pytest.raises(ValueError):
        api.ps2000aSetDataBuffer(1, "PS2000A_CHANNEL_A", make(), 0, "PS2000A_RATIO_MODE_NONE")
    assert stub.calls == []


def test_run_block(api: PicosdkApi, stub: _StubLib) -> None:
    assert api.ps2000aRunBlock(1, 100, 1900, 5, 0, 0) == (0, 3)  # PG §3.37
    assert stub.calls == [
        (
            "ps2000aRunBlock",
            (
                (c_int16, 1),  # handle
                (c_int32, 100),  # noOfPreTriggerSamples
                (c_int32, 1900),  # noOfPostTriggerSamples
                (c_uint32, 5),  # timebase
                (c_int16, 0),  # oversample
                _byref(c_int32, 0),  # timeIndisposedMs
                (c_uint32, 0),  # segmentIndex
                None,  # lpReady
                None,  # pParameter
            ),
        )
    ]


def test_is_ready(api: PicosdkApi, stub: _StubLib) -> None:
    assert api.ps2000aIsReady(1) == (0, 1)  # PG §3.26
    assert stub.calls == [("ps2000aIsReady", ((c_int16, 1), _byref(c_int16, 0)))]


def test_get_values(api: PicosdkApi, stub: _StubLib) -> None:
    result = api.ps2000aGetValues(1, 0, 2000, 1, "PS2000A_RATIO_MODE_NONE", 0)
    assert result == (0, 1900, 0b10)  # PG §3.18: status, noOfSamples out, overflow
    assert stub.calls == [
        (
            "ps2000aGetValues",
            (
                (c_int16, 1),  # handle
                (c_uint32, 0),  # startIndex
                _byref(c_uint32, 2000),  # noOfSamples in
                (c_uint32, 1),  # downSampleRatio
                (c_int32, 0),  # PS2000A_RATIO_MODE_NONE
                (c_uint32, 0),  # segmentIndex
                _byref(c_int16, 0),  # overflow
            ),
        )
    ]


def test_get_values_overflow_is_unsigned_bit_field(api: PicosdkApi, stub: _StubLib) -> None:
    def write(*args: Any) -> int:
        _out(args[2], 10)
        _out(args[6], -32768)  # bit 15 set
        return 0

    stub.ps2000aGetValues = write  # type: ignore[method-assign]
    assert api.ps2000aGetValues(1, 0, 10, 1, "PS2000A_RATIO_MODE_NONE", 0) == (0, 10, 0x8000)


def test_memory_segments(api: PicosdkApi, stub: _StubLib) -> None:
    assert api.ps2000aMemorySegments(1, 1) == (0, 64000)  # PG §3.29: status, nMaxSamples
    assert stub.calls == [
        ("ps2000aMemorySegments", ((c_int16, 1), (c_uint32, 1), _byref(c_int32, 0)))
    ]
    with pytest.raises(ValueError):
        api.ps2000aMemorySegments(1, -1)  # nSegments is a uint32_t
    assert len(stub.calls) == 1


def test_stop(api: PicosdkApi, stub: _StubLib) -> None:
    assert api.ps2000aStop(1) == (0,)  # PG §3.65
    assert stub.calls == [("ps2000aStop", ((c_int16, 1),))]


# --- status handling, validation ---------------------------------------------------------------


def test_status_is_returned_first_and_uninterpreted(api: PicosdkApi, stub: _StubLib) -> None:
    stub.status = 0x0000000E  # PICO_INVALID_TIMEBASE, passed through
    assert api.ps2000aGetTimebase2(1, 0, 100, 0, 0)[0] == 0x0E
    assert api.ps2000aRunBlock(1, 0, 100, 0, 0, 0)[0] == 0x0E
    assert api.ps2000aStop(1) == (0x0E,)
    assert api.ps2000aOpenUnit(None)[0] == 0x0E


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(
            lambda a: a.ps2000aSetChannel(
                1, "PS2000A_CHANNEL_Z", 1, "PS2000A_DC", "PS2000A_1V", 0.0
            ),
            id="channel",
        ),
        pytest.param(
            lambda a: a.ps2000aSetChannel(
                1, "PS2000A_CHANNEL_A", 1, "PS2000A_XX", "PS2000A_1V", 0.0
            ),
            id="coupling",
        ),
        pytest.param(
            lambda a: a.ps2000aSetChannel(
                1, "PS2000A_CHANNEL_A", 1, "PS2000A_DC", "PS2000A_3V", 0.0
            ),
            id="range",
        ),
        pytest.param(
            lambda a: a.ps2000aSetSimpleTrigger(1, 1, "nope", 0, "PS2000A_RISING", 0, 0),
            id="trigger source",
        ),
        pytest.param(
            lambda a: a.ps2000aSetSimpleTrigger(1, 1, "PS2000A_CHANNEL_A", 0, "UP", 0, 0),
            id="trigger direction",
        ),
        pytest.param(
            lambda a: a.ps2000aSetDataBuffer(
                1, "PS2000A_CHANNEL_Q", np.zeros(4, dtype=np.int16), 0, "PS2000A_RATIO_MODE_NONE"
            ),
            id="buffer channel",
        ),
        pytest.param(
            lambda a: a.ps2000aSetDataBuffer(
                1, "PS2000A_CHANNEL_A", np.zeros(4, dtype=np.int16), 0, "PS2000A_RATIO_MODE_ALL"
            ),
            id="buffer ratio mode",
        ),
        pytest.param(
            lambda a: a.ps2000aGetValues(1, 0, 10, 1, "PS2000A_RATIO_MODE_BOGUS", 0),
            id="get values ratio mode",
        ),
        pytest.param(lambda a: a.ps2000aGetUnitInfo(1, "PICO_NOT_AN_INFO"), id="info"),
    ],
)
def test_unknown_enum_name_raises_value_error_without_calling_the_lib(
    api: PicosdkApi, stub: _StubLib, call: Callable[[PicosdkApi], Any]
) -> None:
    with pytest.raises(ValueError, match="unknown"):
        call(api)
    assert stub.calls == []


def test_missing_enum_table_is_a_value_error_naming_the_table() -> None:
    class Bare:  # a library object without the picosdk enum dicts
        pass

    api = PicosdkApi(lib=Bare())
    with pytest.raises(ValueError, match="no enum table PS2000A_CHANNEL"):
        api.ps2000aSetChannel(1, "PS2000A_CHANNEL_A", 1, "PS2000A_DC", "PS2000A_2V", 0.0)
    with pytest.raises(ValueError, match="no enum table PICO_INFO"):
        api.ps2000aGetUnitInfo(1, "PICO_VARIANT_INFO")


def test_integer_arguments_are_range_checked_not_wrapped(api: PicosdkApi, stub: _StubLib) -> None:
    with pytest.raises(ValueError):
        api.ps2000aSetSimpleTrigger(1, 1, "PS2000A_CHANNEL_A", 40000, "PS2000A_RISING", 0, 0)
    with pytest.raises(ValueError):
        api.ps2000aGetTimebase2(1, -1, 100, 0, 0)
    with pytest.raises(ValueError):
        api.ps2000aCloseUnit(2**15)
    with pytest.raises(ValueError):
        api.ps2000aCloseUnit(True)
    assert stub.calls == []


# --- the library is looked up by C function name -----------------------------------------------


def test_functions_are_looked_up_by_c_name(api: PicosdkApi, stub: _StubLib) -> None:
    api.ps2000aStop(1)
    api.ps2000aPingUnit(1)
    assert [name for name, _ in stub.calls] == ["ps2000aStop", "ps2000aPingUnit"]


def test_missing_library_function_is_an_attribute_error() -> None:
    class Bare:
        PICO_INFO: dict[str, int] = {}

    with pytest.raises(AttributeError, match="ps2000aStop"):
        PicosdkApi(lib=Bare()).ps2000aStop(1)


# --- the real ctypes path: C function pointers with picosdk's argtypes ---------------------------
#
# `_StubLib` is called with the ctypes objects the adapter builds, so it cannot tell whether
# ctypes would accept them. `_CFuncLib` can: each function is a `CFUNCTYPE(c_uint32, *argtypes)`
# call target, with the argtypes copied from the `picosdk:` lines of docs/api_reference.md, so
# `c_char_p`/`c_void_p` conversion, `byref` and `data_as` are exercised as against the real
# library, and the Python "driver" behind it only ever sees raw addresses and C values.

_API_REFERENCE = Path(__file__).resolve().parent.parent / "docs" / "api_reference.md"
_PICOSDK_LINE = re.compile(
    r"^picosdk: ps2000a\.(ps2000a\w+), argtypes = \[([^\]]*)\], restype = c_uint32", re.M
)
_USED_FUNCTIONS = (
    "ps2000aEnumerateUnits",
    "ps2000aOpenUnit",
    "ps2000aCloseUnit",
    "ps2000aGetUnitInfo",
    "ps2000aPingUnit",
    "ps2000aFlashLed",
    "ps2000aMaximumValue",
    "ps2000aMinimumValue",
    "ps2000aSetChannel",
    "ps2000aGetTimebase2",
    "ps2000aSetSimpleTrigger",
    "ps2000aSetDataBuffer",
    "ps2000aRunBlock",
    "ps2000aIsReady",
    "ps2000aGetValues",
    "ps2000aStop",
    "ps2000aMemorySegments",
)


def _argtypes_from_the_reference() -> dict[str, list[Any]]:
    text = _API_REFERENCE.read_text(encoding="utf-8")
    table: dict[str, list[Any]] = {}
    for name, types_text in _PICOSDK_LINE.findall(text):
        table[name] = [getattr(ctypes, t.strip()) for t in types_text.split(",") if t.strip()]
    return table


def _write(address: int | None, ctype: Any, value: Any) -> None:
    """Write through an out-pointer the way C code does."""
    assert address, "NULL out pointer"
    ctypes.cast(address, ctypes.POINTER(ctype))[0] = value


def _read(address: int | None, ctype: Any) -> Any:
    assert address, "NULL pointer"
    return ctypes.cast(address, ctypes.POINTER(ctype))[0]


class _CFuncLib:
    """Library object whose functions are C function pointers; a tiny two-channel scope behind.

    Out parameters, strings and data buffers are written through raw addresses, never through
    Python objects, so a wrongly built argument shows up as a wrong value, a crash or an error
    collected in `errors` (an exception cannot propagate through a C callback).
    """

    PS2000A_CHANNEL = _StubLib.PS2000A_CHANNEL
    PS2000A_COUPLING = _StubLib.PS2000A_COUPLING
    PS2000A_RANGE = _StubLib.PS2000A_RANGE
    PS2000A_THRESHOLD_DIRECTION = _StubLib.PS2000A_THRESHOLD_DIRECTION
    PS2000A_RATIO_MODE = _StubLib.PS2000A_RATIO_MODE
    PICO_INFO = _StubLib.PICO_INFO

    INFO = {  # code -> string the scope reports
        0: "1.2.3.4",
        1: "2.0",
        2: "1",
        3: "2207BMSO",
        4: "KJL87/006",
        5: "01Jan26",
        6: "1.0",
        7: "1",
        8: "1",
        9: "0.5",
        10: "0.6",
    }
    SERIALS = "AQ005/139,VDR61/356"
    PICO_OK, PICO_NOT_FOUND, PICO_INVALID_CHANNEL = 0, 3, 0x10
    RANGE_BY_CODE = {code: name for name, code in PS2000A_RANGE.items()}

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []  # (function, C values received)
        self.errors: list[str] = []
        self.opened_serial: bytes | None = None
        self.buffers: dict[int, tuple[int, int]] = {}  # channel code -> (address, length)
        self.enabled: dict[int, tuple[int, int, int]] = {}  # channel -> (coupling, range, enabled)
        self.ready_polls = 2
        self.total = 0
        self._keep: list[Any] = []  # the native thunks must outlive their function pointers
        argtypes = _argtypes_from_the_reference()
        for name in _USED_FUNCTIONS:
            assert name in argtypes, f"no picosdk: line for {name} in docs/api_reference.md"
            setattr(self, name, self._native(name, argtypes[name]))

    def _native(self, name: str, argtypes: list[Any]) -> Any:
        method = getattr(self, "_c_" + name)

        def guarded(*args: Any) -> int:
            self.calls.append((name, args))
            try:
                return int(method(*args))
            except BaseException as exc:  # a callback must not raise into C
                self.errors.append(f"{name}: {type(exc).__name__}: {exc}")
                return 0x7FFFFFFF

        # A C callee receives a `char *` as an address; as a `c_char_p` callback parameter ctypes
        # would hand it a bytes copy, to which nothing can be written. So the thunk takes
        # `c_void_p` where picosdk declares `c_char_p`, while the function pointer the adapter
        # calls (built from the thunk's address) has exactly picosdk's argtypes.
        raw_types = [ctypes.c_void_p if t is ctypes.c_char_p else t for t in argtypes]
        thunk = ctypes.CFUNCTYPE(ctypes.c_uint32, *raw_types)(guarded)
        self._keep.append(thunk)
        address = ctypes.cast(thunk, ctypes.c_void_p).value
        assert address
        return ctypes.CFUNCTYPE(ctypes.c_uint32, *argtypes)(address)

    # -- the functions: addresses in, values out -------------------------------------------

    def _c_ps2000aEnumerateUnits(self, count: int, serials: int, serial_lth: int) -> int:
        assert _read(serial_lth, c_int16) == 1024  # in: the buffer length
        data = self.SERIALS.encode("ascii")
        ctypes.memmove(serials, data + b"\0", len(data) + 1)
        _write(count, c_int16, 2)
        _write(serial_lth, c_int16, len(data))
        return self.PICO_OK

    def _c_ps2000aOpenUnit(self, handle: int, serial: int | None) -> int:
        self.opened_serial = None if serial is None else ctypes.string_at(serial)
        if self.opened_serial not in (None, b"AQ005/139", b"VDR61/356"):
            _write(handle, c_int16, 0)
            return self.PICO_NOT_FOUND
        _write(handle, c_int16, 1)
        return self.PICO_OK

    def _c_ps2000aCloseUnit(self, handle: int) -> int:
        assert handle == 1
        return self.PICO_OK

    def _c_ps2000aGetUnitInfo(
        self, handle: int, string: int, string_length: int, required: int, info: int
    ) -> int:
        data = self.INFO[info].encode("ascii")
        assert string_length >= len(data) + 1
        ctypes.memmove(string, data + b"\0", len(data) + 1)
        _write(required, c_int16, len(data) + 1)
        return self.PICO_OK

    def _c_ps2000aPingUnit(self, handle: int) -> int:
        return self.PICO_OK

    def _c_ps2000aFlashLed(self, handle: int, start: int) -> int:
        return self.PICO_OK

    def _c_ps2000aMaximumValue(self, handle: int, value: int) -> int:
        _write(value, c_int16, 32512)
        return self.PICO_OK

    def _c_ps2000aMinimumValue(self, handle: int, value: int) -> int:
        _write(value, c_int16, -32512)
        return self.PICO_OK

    def _c_ps2000aSetChannel(
        self, handle: int, channel: int, enabled: int, coupling: int, rng: int, offset: float
    ) -> int:
        if channel in (2, 3):  # channels C and D: a two-channel scope refuses them
            return self.PICO_INVALID_CHANNEL
        self.enabled[channel] = (coupling, rng, enabled)
        return self.PICO_OK

    def _c_ps2000aGetTimebase2(
        self,
        handle: int,
        timebase: int,
        no_samples: int,
        interval: int,
        oversample: int,
        max_samples: int,
        segment: int,
    ) -> int:
        _write(interval, c_float, max(timebase - 2, 1) * 8.0)  # PG §2.7, 1 GS/s table, ns
        _write(max_samples, c_int32, 32768)
        return self.PICO_OK

    def _c_ps2000aSetSimpleTrigger(self, *args: Any) -> int:
        return self.PICO_OK

    def _c_ps2000aSetDataBuffer(
        self, handle: int, channel: int, buffer: int, length: int, segment: int, mode: int
    ) -> int:
        assert buffer, "NULL buffer"
        self.buffers[channel] = (buffer, length)
        return self.PICO_OK

    def _c_ps2000aRunBlock(
        self,
        handle: int,
        pre: int,
        post: int,
        timebase: int,
        oversample: int,
        time_indisposed: int,
        segment: int,
        callback: int | None,
        parameter: int | None,
    ) -> int:
        assert callback is None and parameter is None  # NULL: poll with ps2000aIsReady
        self.total = pre + post
        self.ready_polls = 2
        _write(time_indisposed, c_int32, 7)
        return self.PICO_OK

    def _c_ps2000aIsReady(self, handle: int, ready: int) -> int:
        _write(ready, c_int16, int(self.ready_polls <= 0))
        self.ready_polls -= 1
        return self.PICO_OK

    def _c_ps2000aGetValues(
        self,
        handle: int,
        start: int,
        no_of_samples: int,
        ratio: int,
        mode: int,
        segment: int,
        overflow: int,
    ) -> int:
        requested = _read(no_of_samples, c_uint32)  # in: how many were asked for
        n = min(requested, self.total)
        for channel, (address, length) in self.buffers.items():
            assert length >= n
            samples = (np.arange(n) * (channel + 1) % 30000).astype(np.int16)
            ctypes.memmove(address, samples.ctypes.data, 2 * n)  # the driver writes raw memory
        _write(no_of_samples, c_uint32, n)
        _write(overflow, c_int16, 0b10)  # channel B
        return self.PICO_OK

    def _c_ps2000aStop(self, handle: int) -> int:
        return self.PICO_OK

    def _c_ps2000aMemorySegments(self, handle: int, segments: int, n_max_samples: int) -> int:
        _write(n_max_samples, c_int32, 64000)
        return self.PICO_OK


def _decoded(lib: _CFuncLib, name: str) -> list[tuple[Any, ...]]:
    return [args for called, args in lib.calls if called == name]


def test_cfunc_lib_argtypes_come_from_the_reference_and_cover_the_adapter() -> None:
    table = _argtypes_from_the_reference()
    assert table["ps2000aGetValues"] == [
        ctypes.c_int16,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    adapter_functions = {
        name
        for name in vars(PicosdkApi)
        if name.startswith("ps2000a") and callable(getattr(PicosdkApi, name))
    }
    assert adapter_functions <= set(_USED_FUNCTIONS)  # every adapter method runs on this path


def test_adapter_calls_through_real_function_pointers() -> None:
    lib = _CFuncLib()
    api = PicosdkApi(lib=lib)
    assert api.ps2000aEnumerateUnits() == (0, 2, "AQ005/139,VDR61/356")
    assert api.ps2000aOpenUnit(None) == (0, 1)
    assert lib.opened_serial is None  # None became a NULL c_char_p
    assert api.ps2000aOpenUnit("VDR61/356") == (0, 1)
    assert lib.opened_serial == b"VDR61/356"
    assert api.ps2000aOpenUnit("NOPE") == (3, 0)
    assert api.ps2000aGetUnitInfo(1, "PICO_BATCH_AND_SERIAL") == (0, "KJL87/006")
    assert api.ps2000aGetUnitInfo(1, "PICO_FIRMWARE_VERSION_2") == (0, "0.6")
    assert api.ps2000aMaximumValue(1) == (0, 32512)
    assert api.ps2000aMinimumValue(1) == (0, -32512)
    assert api.ps2000aGetTimebase2(1, 127, 2000, 0, 0) == (0, 1000.0, 32768)
    assert api.ps2000aSetChannel(1, "PS2000A_CHANNEL_B", 1, "PS2000A_AC", "PS2000A_5V", 0.0) == (0,)
    assert api.ps2000aSetChannel(1, "PS2000A_CHANNEL_C", 0, "PS2000A_DC", "PS2000A_1V", 0.0) == (
        0x10,
    )
    assert api.ps2000aRunBlock(1, 100, 1900, 127, 0, 0) == (0, 7)
    assert api.ps2000aIsReady(1) == (0, 0)
    assert api.ps2000aMemorySegments(1, 1) == (0, 64000)
    assert api.ps2000aPingUnit(1) == (0,)
    assert api.ps2000aFlashLed(1, 5) == (0,)
    assert api.ps2000aStop(1) == (0,)
    assert api.ps2000aCloseUnit(1) == (0,)
    assert lib.errors == []
    assert lib.enabled[1] == (0, 8, 1)  # AC = 0, PS2000A_5V = 8, enabled
    run_block = _decoded(lib, "ps2000aRunBlock")[0]
    assert run_block[:5] == (1, 100, 1900, 127, 0) and run_block[5]  # then the out address
    assert run_block[6:] == (0, None, None)  # segment 0, lpReady NULL, pParameter NULL


def test_data_buffer_pointer_and_get_values_write_through_the_raw_address() -> None:
    lib = _CFuncLib()
    api = PicosdkApi(lib=lib)
    buffer = np.zeros(50, dtype=np.int16)
    assert api.ps2000aSetDataBuffer(
        1, "PS2000A_CHANNEL_B", buffer, 0, "PS2000A_RATIO_MODE_NONE"
    ) == (0,)
    assert lib.buffers[1] == (buffer.ctypes.data, 50)  # the pointer is the array's own memory
    assert api.ps2000aRunBlock(1, 0, 50, 3, 0, 0)[0] == 0
    assert api.ps2000aGetValues(1, 0, 50, 1, "PS2000A_RATIO_MODE_NONE", 0) == (0, 50, 0b10)
    assert buffer.tolist() == [i * 2 for i in range(50)]  # written by "C", visible in numpy
    assert lib.errors == []


def test_plug_runs_end_to_end_on_the_real_ctypes_path(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = types.SimpleNamespace(monotonic=lambda: 0.0, sleep=lambda seconds: None)
    monkeypatch.setattr(plug_module, "time", clock)  # polling never waits
    lib = _CFuncLib()
    plug = PicoScope2000Plug("AQ005/139", api=PicosdkApi(lib=lib))
    assert lib.opened_serial == b"AQ005/139"
    assert plug.serial == "KJL87/006" and plug.variant == "2207BMSO"
    assert plug.info["PICO_DRIVER_VERSION"] == "1.2.3.4"
    assert (plug.max_adc, plug.min_adc) == (32512, -32512)

    capture = Capture(
        channels=(Channel(ch=1, range=2 * V), Channel(ch=2, range=5 * V, coupling="AC")),
        sample_interval=1 * us,
        pre_samples=100,
        post_samples=1900,
        trigger=Edge(source=2, level=1.0 * V, direction="FALLING", auto_ms=500),
    )
    plug.apply_capture(capture)
    assert plug.channel_count == 2  # channel C was refused with PICO_INVALID_CHANNEL
    plug.single()
    assert plug.time_indisposed_ms == 7
    plug.wait_ready()
    a, b = plug.read_waveform(1), plug.read_waveform(2)
    plug.stop()
    plug.tearDown()

    assert lib.errors == []
    # C values the library received, in the manual's argument order (PG §3.39 ... §3.56)
    assert [c[1:] for c in _decoded(lib, "ps2000aSetChannel")[:2]] == [
        (0, 1, 1, 7, 0.0),  # A: PS2000A_CHANNEL_A = 0, enabled, DC = 1, PS2000A_2V = 7
        (1, 1, 0, 8, 0.0),  # B: AC = 0, PS2000A_5V = 8
    ]
    assert _decoded(lib, "ps2000aSetSimpleTrigger") == [
        (1, 1, 1, round(1.0 / 5 * 32512), 3, 0, 500)  # B, threshold counts, FALLING = 3
    ]
    assert plug.timebase == 127 and plug.sample_interval_s == pytest.approx(1e-6)
    assert [(c[1], c[2]) for c in _decoded(lib, "ps2000aGetTimebase2")] == [
        (127, 2000),
        (126, 2000),
    ]
    assert sorted(lib.buffers) == [0, 1]  # one registered buffer per enabled channel
    assert all(length == 2000 for _, length in lib.buffers.values())
    assert [c[:2] + c[3:6] for c in _decoded(lib, "ps2000aGetValues")] == [
        (1, 0, 1, 0, 0)  # handle, start, ratio 1, RATIO_MODE_NONE = 0, segment 0
    ]
    assert len(_decoded(lib, "ps2000aGetValues")) == 1  # one call serves both channels
    assert a.raw.tolist() == [i % 30000 for i in range(2000)]  # A: i * 1, written through C
    assert b.raw.tolist() == [i * 2 % 30000 for i in range(2000)]  # B: i * 2: no channel mix-up
    assert (a.meta.overflow, b.meta.overflow) == (False, True)  # PG §3.18 bit field, B = 0b10
    assert a.meta.range_v == 2.0 and b.meta.range_v == 5.0 and b.meta.coupling == "AC"
    assert b.v[7] == pytest.approx(b.raw[7] * 5.0 / 32512)
    assert [name for name, _ in lib.calls][-2:] == ["ps2000aStop", "ps2000aCloseUnit"]
    assert _decoded(lib, "ps2000aCloseUnit") == [(1,)]


def test_plug_open_failure_on_the_real_ctypes_path() -> None:
    lib = _CFuncLib()
    with pytest.raises(PicoError) as excinfo:
        PicoScope2000Plug("NOPE", api=PicosdkApi(lib=lib))
    assert excinfo.value.name == "PICO_NOT_FOUND"
    assert lib.errors == []
    assert PicoScope2000Plug.list_units(PicosdkApi(lib=lib)) == ["AQ005/139", "VDR61/356"]


# --- lazy import of picosdk.ps2000a -------------------------------------------------------------


class _CountingModule(types.ModuleType):
    """Stands in for `picosdk.ps2000a`; counts how often `ps2000a` is fetched from it."""

    def __init__(self, lib: object) -> None:
        super().__init__("picosdk.ps2000a")
        self._lib = lib
        self.fetches = 0

    def __getattr__(self, name: str) -> object:
        if name == "ps2000a":
            self.fetches += 1
            return self._lib
        raise AttributeError(name)


def test_constructor_does_not_import_picosdk_ps2000a(
    monkeypatch: pytest.MonkeyPatch, stub: _StubLib
) -> None:
    module = _CountingModule(stub)
    monkeypatch.setitem(sys.modules, "picosdk.ps2000a", module)
    api = PicosdkApi()
    assert module.fetches == 0
    assert api.ps2000aStop(1) == (0,)  # first call imports lazily ...
    assert module.fetches == 1
    api.ps2000aPingUnit(1)  # ... and only once
    assert module.fetches == 1
    assert [name for name, _ in stub.calls] == ["ps2000aStop", "ps2000aPingUnit"]


def test_first_call_attempts_the_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "picosdk.ps2000a", raising=False)
    api = PicosdkApi()
    assert "picosdk.ps2000a" not in sys.modules  # construction imported nothing
    # `None` in sys.modules makes the import statement raise ImportError, on any machine,
    # whether or not the native library is installed.
    monkeypatch.setitem(sys.modules, "picosdk.ps2000a", None)
    with pytest.raises(ImportError):
        api.ps2000aStop(1)


def test_import_error_propagates_with_its_own_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Boom(types.ModuleType):
        def __getattr__(self, name: str) -> object:
            raise RuntimeError("PicoSDK (ps2000a) not found, check LD_LIBRARY_PATH")

    monkeypatch.setitem(sys.modules, "picosdk.ps2000a", _Boom("picosdk.ps2000a"))
    with pytest.raises((RuntimeError, ImportError), match="not found"):
        PicosdkApi().ps2000aStop(1)


def test_injected_lib_imports_nothing_from_picosdk_ps2000a(
    monkeypatch: pytest.MonkeyPatch, stub: _StubLib
) -> None:
    monkeypatch.delitem(sys.modules, "picosdk.ps2000a", raising=False)
    api = PicosdkApi(lib=stub)
    api.ps2000aStop(1)
    api.ps2000aSetChannel(1, "PS2000A_CHANNEL_A", 1, "PS2000A_DC", "PS2000A_1V", 0.0)
    assert "picosdk.ps2000a" not in sys.modules


def test_importing_driver_does_not_load_picosdk_ps2000a() -> None:
    code = (
        "import sys\n"
        "import picoscope_2000_openhtf.driver\n"
        "assert 'picosdk.ps2000a' not in sys.modules\n"
        "assert 'picosdk.constants' in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True)


# --- status helpers ------------------------------------------------------------------------------


def test_status_name_known_codes() -> None:
    assert status_name(0) == "PICO_OK"
    assert status_name(0x0E) == "PICO_INVALID_TIMEBASE"
    assert status_name(0x25) == "PICO_NO_SAMPLES_AVAILABLE"


def test_status_name_unknown_code_falls_back_to_hex() -> None:
    assert status_name(0x7ABCDEF0) == "0x7ABCDEF0"
    assert status_name(0x0F00D) == "0x0000F00D"
    assert status_name(-1) == "0xFFFFFFFF"


def test_status_code() -> None:
    assert status_code("PICO_OK") == 0
    assert status_code("PICO_INVALID_HANDLE") == 0x0C
    assert status_name(status_code("PICO_BUSY")) == "PICO_BUSY"
    with pytest.raises(KeyError):
        status_code("PICO_HANDLE_INVALID")  # spelled so in three manual sections, not in the header


def test_module_exports() -> None:
    assert set(driver.__all__) == {"Ps2000aApi", "PicosdkApi", "status_code", "status_name"}
