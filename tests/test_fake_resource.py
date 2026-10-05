"""Tests for the hardware-free fake driver (SPEC sections 6 and 7)."""

import ast
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pytest
from picosdk.constants import PICO_INFO, PICO_STATUS

from picoscope_2000_openhtf import fake_resource
from picoscope_2000_openhtf.fake_resource import STATUS, FakePs2000a

A = "PS2000A_CHANNEL_A"
B = "PS2000A_CHANNEL_B"
C = "PS2000A_CHANNEL_C"
NONE = "PS2000A_RATIO_MODE_NONE"
OK = STATUS["PICO_OK"]

Int16Array = npt.NDArray[np.int16]


def _open(fake: FakePs2000a, serial: str | None = None) -> int:
    status, handle = fake.ps2000aOpenUnit(serial)
    assert status == OK
    return handle


def _channel(
    fake: FakePs2000a, handle: int, channel: str = A, rng: str = "PS2000A_2V", enabled: int = 1
) -> None:
    assert fake.ps2000aSetChannel(handle, channel, enabled, "PS2000A_DC", rng, 0.0) == (OK,)


def _timebase_for(interval_s: float) -> int:
    # 1 GS/s table of PG §2.7: n >= 3 gives (n - 2) / 125e6 s
    return round(interval_s * 125e6) + 2


def _capture(
    fake: FakePs2000a,
    handle: int,
    *,
    pre: int = 100,
    post: int = 1900,
    interval_s: float = 1e-6,
    channels: tuple[str, ...] = (A,),
    ranges: tuple[str, ...] = ("PS2000A_2V",),
    trigger: tuple[str, int, str] | None = None,
    poll: bool = True,
) -> dict[str, Int16Array]:
    """Configure, run and read one block; returns the buffers by channel name."""
    for name, rng in zip(channels, ranges, strict=True):
        _channel(fake, handle, name, rng)
    if trigger is None:
        assert fake.ps2000aSetSimpleTrigger(handle, 0, A, 0, "PS2000A_RISING", 0, 0) == (OK,)
    else:
        source, threshold, direction = trigger
        assert fake.ps2000aSetSimpleTrigger(handle, 1, source, threshold, direction, 0, 0) == (OK,)
    buffers = {name: np.zeros(pre + post, dtype=np.int16) for name in channels}
    for name, buf in buffers.items():
        assert fake.ps2000aSetDataBuffer(handle, name, buf, 0, NONE) == (OK,)
    timebase = _timebase_for(interval_s)
    status, _ = fake.ps2000aRunBlock(handle, pre, post, timebase, 0, 0)
    assert status == OK
    if poll:
        while fake.ps2000aIsReady(handle)[1] == 0:
            pass
    return buffers


def _get(fake: FakePs2000a, handle: int, n: int = 2000) -> tuple[int, int, int]:
    return fake.ps2000aGetValues(handle, 0, n, 1, NONE, 0)


def _rising_edges(raw: Int16Array) -> npt.NDArray[np.intp]:
    high = raw > raw.max() // 2
    return np.flatnonzero(~high[:-1] & high[1:]) + 1


# --- STATUS table and import isolation ---------------------------------------------------


def test_status_matches_picosdk_for_every_entry() -> None:
    for name, value in STATUS.items():
        assert PICO_STATUS[name] == value, name


def test_status_has_the_codes_the_spec_lists() -> None:
    required = {
        "PICO_OK",
        "PICO_NOT_FOUND",
        "PICO_INVALID_HANDLE",
        "PICO_INVALID_CHANNEL",
        "PICO_INVALID_VOLTAGE_RANGE",
        "PICO_INVALID_COUPLING",
        "PICO_INVALID_TIMEBASE",
        "PICO_INVALID_PARAMETER",
        "PICO_NO_SAMPLES_AVAILABLE",
        "PICO_INVALID_INFO",
        "PICO_INFO_UNAVAILABLE",
        "PICO_TOO_MANY_SAMPLES",
        "PICO_BUSY",
        "PICO_INVALID_TRIGGER_CHANNEL",
    }
    assert required <= set(STATUS)
    assert STATUS["PICO_OK"] == 0
    assert "PICO_HANDLE_INVALID" not in STATUS  # the header has only PICO_INVALID_HANDLE


def test_import_isolation_subprocess() -> None:
    code = (
        "import json, sys\n"
        "import picoscope_2000_openhtf.fake_resource\n"
        "loaded = sorted(m for m in sys.modules if m == 'picosdk' or m.startswith('picosdk.')"
        " or m == 'openhtf' or m.startswith('openhtf.'))\n"
        "print(json.dumps({'loaded': loaded}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {"loaded": []}


def test_import_isolation_ast() -> None:
    source = Path(fake_resource.__file__).read_text(encoding="utf-8")
    allowed = {"numpy"} | set(sys.stdlib_module_names)
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import of the package is forbidden"
            assert node.module is not None
            found.add(node.module)
    assert {"numpy", "numpy.typing"} <= found
    for module in found:
        assert module.split(".")[0] in allowed, module
    assert not {m for m in found if m.startswith(("picosdk", "openhtf", "picoscope_2000"))}


# --- construction ------------------------------------------------------------------------


def test_defaults_and_public_attributes() -> None:
    fake = FakePs2000a()
    assert fake.log == []
    assert fake.reject == {}
    assert fake.units == {}
    assert fake.closed_handles == []


@pytest.mark.parametrize(
    "kw",
    [
        {"serials": ("A", "A")},
        {"signal": "sine"},
        {"defect": "bad"},
        {"clock_hz": 0.0},
        {"memory_samples": 0},
        {"max_rate_hz": -1.0},
        {"ready_after": -1},
    ],
)
def test_constructor_rejects_bad_arguments(kw: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="invalid FakePs2000a arguments"):
        FakePs2000a(**kw)  # type: ignore[arg-type]


# --- enumerate / open / close ------------------------------------------------------------


def test_enumerate_lists_unopened_serials() -> None:
    fake = FakePs2000a(serials=("AQ005/139", "VDR61/356"))
    assert fake.ps2000aEnumerateUnits() == (OK, 2, "AQ005/139,VDR61/356")  # PG §3.4
    _open(fake, "AQ005/139")
    assert fake.ps2000aEnumerateUnits() == (OK, 1, "VDR61/356")


def test_enumerate_without_units() -> None:
    assert FakePs2000a(serials=()).ps2000aEnumerateUnits() == (OK, 0, "")


def test_open_none_takes_first_unopened_then_next() -> None:
    fake = FakePs2000a(serials=("S1", "S2"))
    assert fake.ps2000aOpenUnit(None) == (OK, 1)
    assert fake.units[1].serial == "S1"
    assert fake.ps2000aOpenUnit(None) == (OK, 2)
    assert fake.units[2].serial == "S2"
    assert fake.ps2000aOpenUnit(None) == (STATUS["PICO_NOT_FOUND"], 0)


def test_open_by_serial() -> None:
    fake = FakePs2000a(serials=("S1", "S2"))
    assert fake.ps2000aOpenUnit("S2") == (OK, 1)
    assert fake.units[1].serial == "S2"
    assert fake.ps2000aOpenUnit("S2") == (STATUS["PICO_NOT_FOUND"], 0)  # already open
    assert fake.ps2000aOpenUnit("NOPE") == (STATUS["PICO_NOT_FOUND"], 0)
    assert fake.ps2000aOpenUnit("s1") == (STATUS["PICO_NOT_FOUND"], 0)  # case-sensitive


def test_handles_start_at_one_and_are_never_reused() -> None:
    fake = FakePs2000a()
    h1 = _open(fake)
    assert h1 == 1
    assert fake.ps2000aCloseUnit(h1) == (OK,)
    h2 = _open(fake)
    assert h2 == 2


def test_close_forgets_handle_and_serial_becomes_unopened() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    assert fake.ps2000aEnumerateUnits() == (OK, 0, "")
    assert fake.ps2000aCloseUnit(handle) == (OK,)
    assert fake.closed_handles == [handle]
    assert handle not in fake.units
    assert fake.ps2000aEnumerateUnits() == (OK, 1, "FAKE0/001")
    assert fake.ps2000aCloseUnit(handle) == (STATUS["PICO_INVALID_HANDLE"],)
    assert fake.closed_handles == [handle]


def test_unknown_and_closed_handles_give_invalid_handle() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    fake.ps2000aCloseUnit(handle)
    bad = STATUS["PICO_INVALID_HANDLE"]
    buf = np.zeros(10, dtype=np.int16)
    for h in (handle, 99, 0, -1):
        assert fake.ps2000aCloseUnit(h) == (bad,)
        assert fake.ps2000aGetUnitInfo(h, "PICO_VARIANT_INFO") == (bad, "")
        assert fake.ps2000aPingUnit(h) == (bad,)
        assert fake.ps2000aFlashLed(h, 1) == (bad,)
        assert fake.ps2000aMaximumValue(h) == (bad, 0)
        assert fake.ps2000aMinimumValue(h) == (bad, 0)
        assert fake.ps2000aSetChannel(h, A, 1, "PS2000A_DC", "PS2000A_1V", 0.0) == (bad,)
        assert fake.ps2000aGetTimebase2(h, 3, 10, 0, 0) == (bad, 0.0, 0)
        assert fake.ps2000aSetSimpleTrigger(h, 0, A, 0, "PS2000A_RISING", 0, 0) == (bad,)
        assert fake.ps2000aSetDataBuffer(h, A, buf, 0, NONE) == (bad,)
        assert fake.ps2000aRunBlock(h, 0, 10, 3, 0, 0) == (bad, 0)
        assert fake.ps2000aIsReady(h) == (bad, 0)
        assert fake.ps2000aGetValues(h, 0, 10, 1, NONE, 0) == (bad, 0, 0)
        assert fake.ps2000aStop(h) == (bad,)


def test_unit_info_with_invalid_handle_only_gives_driver_version() -> None:
    fake = FakePs2000a()
    assert fake.ps2000aGetUnitInfo(42, "PICO_DRIVER_VERSION") == (OK, "0.0.0.0-fake")  # PG §3.17


def test_two_units_are_independent() -> None:
    fake = FakePs2000a(serials=("S1", "S2"))
    h1, h2 = _open(fake), _open(fake)
    _channel(fake, h1, A)
    assert fake.units[h1].channels[A].enabled
    assert not fake.units[h2].channels[A].enabled


# --- unit information --------------------------------------------------------------------


def test_unit_info_strings() -> None:
    fake = FakePs2000a(serials=("SER/1",), variant="2207BMSO")
    handle = _open(fake)
    assert fake.ps2000aGetUnitInfo(handle, "PICO_VARIANT_INFO") == (OK, "2207BMSO")
    assert fake.ps2000aGetUnitInfo(handle, "PICO_BATCH_AND_SERIAL") == (OK, "SER/1")
    assert fake.ps2000aGetUnitInfo(handle, "PICO_DRIVER_VERSION") == (OK, "0.0.0.0-fake")
    # every info code of PG §3.17 (0..10) is served and is a PICO_INFO name
    names = [n for n, code in PICO_INFO.items() if code <= 10]
    assert len(names) == 11
    for name in names:
        status, text = fake.ps2000aGetUnitInfo(handle, name)
        assert status == OK
        assert isinstance(text, str)
        assert text


def test_unit_info_unknown_name() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    assert fake.ps2000aGetUnitInfo(handle, "PICO_NOPE") == (STATUS["PICO_INVALID_INFO"], "")
    assert fake.ps2000aGetUnitInfo(handle, "PICO_MAC_ADDRESS")[0] == STATUS["PICO_INVALID_INFO"]


def test_max_min_value_flash_ping() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    assert fake.ps2000aMaximumValue(handle) == (OK, 32512)  # PG §2.3
    assert fake.ps2000aMinimumValue(handle) == (OK, -32512)
    assert fake.ps2000aFlashLed(handle, 5) == (OK,)
    assert fake.ps2000aPingUnit(handle) == (OK,)


# --- SetChannel --------------------------------------------------------------------------


def test_set_channel_stores_state() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    assert fake.ps2000aSetChannel(handle, B, 1, "PS2000A_AC", "PS2000A_500MV", 0.0) == (OK,)
    cfg = fake.units[handle].channels[B]
    assert (cfg.enabled, cfg.coupling, cfg.range) == (True, "PS2000A_AC", "PS2000A_500MV")
    assert fake.ps2000aSetChannel(handle, B, 0, "PS2000A_DC", "PS2000A_1V", 0.0) == (OK,)
    assert not fake.units[handle].channels[B].enabled


@pytest.mark.parametrize(
    "channel",
    ["PS2000A_CHANNEL_A", "PS2000A_CHANNEL_B"],
)
@pytest.mark.parametrize(
    "rng",
    [
        "PS2000A_20MV",
        "PS2000A_50MV",
        "PS2000A_100MV",
        "PS2000A_200MV",
        "PS2000A_500MV",
        "PS2000A_1V",
        "PS2000A_2V",
        "PS2000A_5V",
        "PS2000A_10V",
        "PS2000A_20V",
    ],
)
def test_set_channel_accepts_all_ten_ranges(channel: str, rng: str) -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    for coupling in ("PS2000A_AC", "PS2000A_DC"):
        assert fake.ps2000aSetChannel(handle, channel, 1, coupling, rng, 0.0) == (OK,)


def test_set_channel_validates_names() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    assert fake.ps2000aSetChannel(handle, "A", 1, "PS2000A_DC", "PS2000A_1V", 0.0) == (
        STATUS["PICO_INVALID_CHANNEL"],
    )
    assert fake.ps2000aSetChannel(handle, A, 1, "DC", "PS2000A_1V", 0.0) == (
        STATUS["PICO_INVALID_COUPLING"],
    )
    # PICO_10MV and PICO_50V exist in picosdk but not in the manual's list (PG §3.39)
    for bad in ("PS2000A_10MV", "PS2000A_50V", "1V", ""):
        assert fake.ps2000aSetChannel(handle, A, 1, "PS2000A_DC", bad, 0.0) == (
            STATUS["PICO_INVALID_VOLTAGE_RANGE"],
        )
    assert not fake.units[handle].channels[A].enabled  # nothing stored on error


def test_two_channel_variant_rejects_c_and_d() -> None:
    fake = FakePs2000a(variant="2207BMSO")
    handle = _open(fake)
    for name in (C, "PS2000A_CHANNEL_D"):
        assert fake.ps2000aSetChannel(handle, name, 1, "PS2000A_DC", "PS2000A_1V", 0.0) == (
            STATUS["PICO_INVALID_CHANNEL"],
        )


def test_four_channel_variant_accepts_c_and_d() -> None:
    fake = FakePs2000a(variant="2408B")
    handle = _open(fake)
    for name in (A, B, C, "PS2000A_CHANNEL_D"):
        assert fake.ps2000aSetChannel(handle, name, 1, "PS2000A_DC", "PS2000A_1V", 0.0) == (OK,)


# --- GetTimebase2 ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("timebase", "interval_ns"),
    [(0, 1.0), (1, 2.0), (2, 4.0), (3, 8.0), (4, 16.0), (127, 1000.0), (1002, 8000.0)],
)
def test_timebase_table_1gs(timebase: int, interval_ns: float) -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _channel(fake, handle, A)  # n = 0 needs a single enabled channel (PG §2.7 footnote)
    status, interval, _ = fake.ps2000aGetTimebase2(handle, timebase, 100, 0, 0)
    assert status == OK
    assert interval == interval_ns  # PG §2.7, exact (float32 holds these integers)


def test_timebase_table_500ms() -> None:
    fake = FakePs2000a(max_rate_hz=500e6)
    handle = _open(fake)
    _channel(fake, handle, A)
    intervals = [fake.ps2000aGetTimebase2(handle, n, 10, 0, 0)[1] for n in (0, 1, 2, 3, 4)]
    assert intervals == [2.0, 4.0, 8.0, 16.0, 32.0]  # PG §2.7, 500 MS/s models


def test_timebase_zero_needs_single_channel() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _channel(fake, handle, A)
    _channel(fake, handle, B)
    assert fake.ps2000aGetTimebase2(handle, 0, 10, 0, 0)[0] == STATUS["PICO_INVALID_TIMEBASE"]
    assert fake.ps2000aGetTimebase2(handle, 1, 10, 0, 0)[0] == OK
    _channel(fake, handle, B, enabled=0)
    assert fake.ps2000aGetTimebase2(handle, 0, 10, 0, 0)[0] == OK


def test_timebase_out_of_range() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _channel(fake, handle, A)
    assert fake.ps2000aGetTimebase2(handle, -1, 10, 0, 0)[0] == STATUS["PICO_INVALID_TIMEBASE"]
    assert fake.ps2000aGetTimebase2(handle, 2**32, 10, 0, 0)[0] == STATUS["PICO_INVALID_TIMEBASE"]
    assert fake.ps2000aGetTimebase2(handle, 2**32 - 1, 10, 0, 0)[0] == OK


def test_timebase_max_samples_follows_enabled_channels() -> None:
    fake = FakePs2000a(variant="2408B", memory_samples=64000)
    handle = _open(fake)
    expected = {1: 64000, 2: 32000, 3: 16000, 4: 16000}  # PG §2.6.1
    names = (A, B, C, "PS2000A_CHANNEL_D")
    for count in (1, 2, 3, 4):
        for i, name in enumerate(names):
            _channel(fake, handle, name, enabled=int(i < count))
        status, _, max_samples = fake.ps2000aGetTimebase2(handle, 3, 10, 0, 0)
        assert (status, max_samples) == (OK, expected[count])


def test_timebase_too_many_samples_still_fills_values() -> None:
    fake = FakePs2000a(memory_samples=1000)
    handle = _open(fake)
    _channel(fake, handle, A)
    assert fake.ps2000aGetTimebase2(handle, 3, 1000, 0, 0) == (OK, 8.0, 1000)
    assert fake.ps2000aGetTimebase2(handle, 3, 1001, 0, 0) == (
        STATUS["PICO_TOO_MANY_SAMPLES"],
        8.0,
        1000,
    )


def test_timebase_segment_and_negative_samples() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _channel(fake, handle, A)
    assert fake.ps2000aGetTimebase2(handle, 3, 10, 0, 1)[0] == STATUS["PICO_SEGMENT_OUT_OF_RANGE"]
    assert fake.ps2000aGetTimebase2(handle, 3, -1, 0, 0)[0] == STATUS["PICO_INVALID_PARAMETER"]


def test_timebase_returns_float32_interval() -> None:
    fake = FakePs2000a(max_rate_hz=3e9)  # 1/3 ns is not a float32 number
    handle = _open(fake)
    _channel(fake, handle, A)
    _, interval, _ = fake.ps2000aGetTimebase2(handle, 0, 10, 0, 0)
    assert interval == float(np.float32(interval))
    assert interval != 1e9 / 3e9


# --- SetSimpleTrigger --------------------------------------------------------------------


@pytest.mark.parametrize(
    "direction",
    [
        "PS2000A_ABOVE",
        "PS2000A_BELOW",
        "PS2000A_RISING",
        "PS2000A_FALLING",
        "PS2000A_RISING_OR_FALLING",
    ],
)
def test_trigger_accepts_the_five_directions(direction: str) -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _channel(fake, handle, A)
    assert fake.ps2000aSetSimpleTrigger(handle, 1, A, 8128, direction, 5, 100) == (OK,)
    trigger = fake.units[handle].trigger
    assert (trigger.enabled, trigger.source, trigger.threshold) == (True, A, 8128)
    assert (trigger.direction, trigger.delay, trigger.auto_trigger_ms) == (direction, 5, 100)


def test_trigger_validation() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _channel(fake, handle, A)
    t = fake.ps2000aSetSimpleTrigger
    assert t(handle, 1, "A", 0, "PS2000A_RISING", 0, 0) == (STATUS["PICO_INVALID_CHANNEL"],)
    assert t(handle, 1, C, 0, "PS2000A_RISING", 0, 0) == (STATUS["PICO_INVALID_CHANNEL"],)
    assert t(handle, 1, A, 0, "RISING", 0, 0) == (STATUS["PICO_INVALID_PARAMETER"],)
    assert t(handle, 1, A, 0, "PS2000A_RISING_LOWER", 0, 0) == (STATUS["PICO_INVALID_PARAMETER"],)
    assert t(handle, 1, A, 40000, "PS2000A_RISING", 0, 0) == (STATUS["PICO_INVALID_PARAMETER"],)
    assert t(handle, 1, A, 0, "PS2000A_RISING", 0, -1) == (STATUS["PICO_INVALID_PARAMETER"],)
    assert t(handle, 1, A, 0, "PS2000A_RISING", 0, 32768) == (STATUS["PICO_INVALID_PARAMETER"],)
    assert t(handle, 1, A, 0, "PS2000A_RISING", -1, 0) == (STATUS["PICO_INVALID_PARAMETER"],)
    assert t(handle, 1, A, 0, "PS2000A_RISING", 0, 32767) == (OK,)
    assert not t(handle, 0, "junk", 0, "junk", 0, 0)[0]  # enable=0 ignores the rest
    assert not fake.units[handle].trigger.enabled


def test_trigger_source_must_be_enabled() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _channel(fake, handle, A)
    assert fake.ps2000aSetSimpleTrigger(handle, 1, B, 0, "PS2000A_RISING", 0, 0) == (
        STATUS["PICO_INVALID_TRIGGER_CHANNEL"],
    )


# --- SetDataBuffer -----------------------------------------------------------------------


def test_set_data_buffer_keeps_the_array_itself() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    buf = np.zeros(100, dtype=np.int16)
    assert fake.ps2000aSetDataBuffer(handle, A, buf, 0, NONE) == (OK,)
    assert fake.units[handle].buffers[A] is buf  # PG §3.40: tells the driver where to store


def test_set_data_buffer_validation() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    good = np.zeros(10, dtype=np.int16)
    s = fake.ps2000aSetDataBuffer
    assert s(handle, "A", good, 0, NONE) == (STATUS["PICO_INVALID_CHANNEL"],)
    assert s(handle, C, good, 0, NONE) == (STATUS["PICO_INVALID_CHANNEL"],)
    assert s(handle, A, good, 1, NONE) == (STATUS["PICO_SEGMENT_OUT_OF_RANGE"],)
    assert s(handle, A, good, 0, "NONE") == (STATUS["PICO_INVALID_PARAMETER"],)
    assert s(handle, A, np.zeros(10, dtype=np.int32), 0, NONE) == (
        STATUS["PICO_INVALID_PARAMETER"],
    )
    assert s(handle, A, np.zeros(0, dtype=np.int16), 0, NONE) == (STATUS["PICO_INVALID_PARAMETER"],)
    assert s(handle, A, good, 0, "PS2000A_RATIO_MODE_AGGREGATE") == (
        STATUS["PICO_RATIO_MODE_NOT_SUPPORTED"],
    )
    assert A not in fake.units[handle].buffers


# --- RunBlock / IsReady ------------------------------------------------------------------


def test_run_block_too_many_samples() -> None:
    fake = FakePs2000a(memory_samples=1000)
    handle = _open(fake)
    _channel(fake, handle, A)
    assert fake.ps2000aRunBlock(handle, 500, 501, 3, 0, 0)[0] == STATUS["PICO_TOO_MANY_SAMPLES"]
    assert fake.ps2000aRunBlock(handle, 500, 500, 3, 0, 0)[0] == OK
    _channel(fake, handle, B)  # two channels: half the memory
    assert fake.ps2000aRunBlock(handle, 300, 300, 3, 0, 0)[0] == STATUS["PICO_TOO_MANY_SAMPLES"]
    assert fake.ps2000aRunBlock(handle, 250, 250, 3, 0, 0)[0] == OK


def test_run_block_other_statuses() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    assert fake.ps2000aRunBlock(handle, 0, 10, 3, 0, 0) == (STATUS["PICO_INVALID_CHANNEL"], 0)
    _channel(fake, handle, A)
    _channel(fake, handle, B)
    assert fake.ps2000aRunBlock(handle, 0, 10, 0, 0, 0) == (STATUS["PICO_INVALID_TIMEBASE"], 0)
    assert fake.ps2000aRunBlock(handle, 0, 10, 3, 0, 1) == (STATUS["PICO_SEGMENT_OUT_OF_RANGE"], 0)
    assert fake.ps2000aRunBlock(handle, -1, 10, 3, 0, 0) == (STATUS["PICO_INVALID_PARAMETER"], 0)
    assert fake.ps2000aRunBlock(handle, 0, 0, 3, 0, 0) == (STATUS["PICO_INVALID_PARAMETER"], 0)


def test_run_block_trigger_channel_disabled_after_trigger_setup() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _channel(fake, handle, A)
    _channel(fake, handle, B)
    assert fake.ps2000aSetSimpleTrigger(handle, 1, B, 0, "PS2000A_RISING", 0, 0) == (OK,)
    _channel(fake, handle, B, enabled=0)
    assert fake.ps2000aRunBlock(handle, 0, 10, 3, 0, 0) == (
        STATUS["PICO_INVALID_TRIGGER_CHANNEL"],
        0,
    )


def test_run_block_without_buffers_is_allowed() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _channel(fake, handle, A)
    assert fake.ps2000aRunBlock(handle, 0, 10, 3, 0, 0)[0] == OK


@pytest.mark.parametrize(
    ("total", "timebase", "expected_ms"),
    [(2000, 127, 2), (2001, 127, 3), (1, 3, 1), (65536, 3, 1)],
)
def test_run_block_time_indisposed(total: int, timebase: int, expected_ms: int) -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _channel(fake, handle, A)
    # ceil(total * interval * 1e3): 2000 * 1 us = 2 ms, 2001 * 1 us -> 3 ms, 65536 * 8 ns -> 1 ms
    assert fake.ps2000aRunBlock(handle, 0, total, timebase, 0, 0) == (OK, expected_ms)


def test_is_ready_counts_down() -> None:
    fake = FakePs2000a(ready_after=2)
    handle = _open(fake)
    _channel(fake, handle, A)
    assert fake.ps2000aIsReady(handle) == (OK, 0)  # nothing running
    fake.ps2000aRunBlock(handle, 0, 10, 3, 0, 0)
    assert [fake.ps2000aIsReady(handle) for _ in range(5)] == [
        (OK, 0),
        (OK, 0),
        (OK, 1),
        (OK, 1),
        (OK, 1),
    ]


def test_is_ready_immediately_with_ready_after_zero() -> None:
    fake = FakePs2000a(ready_after=0)
    handle = _open(fake)
    _channel(fake, handle, A)
    fake.ps2000aRunBlock(handle, 0, 10, 3, 0, 0)
    assert fake.ps2000aIsReady(handle) == (OK, 1)


def test_new_run_restarts_the_countdown() -> None:
    fake = FakePs2000a(ready_after=1)
    handle = _open(fake)
    _channel(fake, handle, A)
    fake.ps2000aRunBlock(handle, 0, 10, 3, 0, 0)
    assert [fake.ps2000aIsReady(handle)[1] for _ in range(2)] == [0, 1]
    fake.ps2000aRunBlock(handle, 0, 10, 3, 0, 0)
    assert fake.ps2000aIsReady(handle) == (OK, 0)


# --- GetValues: statuses -----------------------------------------------------------------


def test_get_values_before_ready_is_no_samples_available() -> None:
    fake = FakePs2000a(ready_after=2)
    handle = _open(fake)
    buffers = _capture(fake, handle, poll=False)
    assert _get(fake, handle) == (STATUS["PICO_NO_SAMPLES_AVAILABLE"], 0, 0)  # PG §3.18
    assert not buffers[A].any()
    fake.ps2000aIsReady(handle)
    assert _get(fake, handle)[0] == STATUS["PICO_NO_SAMPLES_AVAILABLE"]
    fake.ps2000aIsReady(handle)
    fake.ps2000aIsReady(handle)
    assert _get(fake, handle)[0] == OK


def test_get_values_without_any_run_is_no_samples_available() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    assert _get(fake, handle)[0] == STATUS["PICO_NO_SAMPLES_AVAILABLE"]


def test_get_values_returns_min_of_requested_and_total() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _capture(fake, handle)
    assert _get(fake, handle, 5000)[1] == 2000
    assert _get(fake, handle, 2000)[1] == 2000
    assert _get(fake, handle, 1500)[1] == 1500
    assert _get(fake, handle, 0)[1] == 0


def test_get_values_start_index() -> None:
    fake = FakePs2000a(signal="ramp")
    handle = _open(fake)
    buffers = _capture(fake, handle)
    assert fake.ps2000aGetValues(handle, 10, 5, 1, NONE, 0) == (OK, 5, 0)
    # ramp = i % 1000 / 1000 * clock_v on a 2 V range
    expected = np.rint(np.arange(10, 15) / 1000 / 2.0 * 32512).astype(np.int16)
    assert np.array_equal(buffers[A][:5], expected)
    assert fake.ps2000aGetValues(handle, 1990, 100, 1, NONE, 0)[1] == 10
    assert (
        fake.ps2000aGetValues(handle, 2000, 1, 1, NONE, 0)[0] == STATUS["PICO_STARTINDEX_INVALID"]
    )
    assert fake.ps2000aGetValues(handle, -1, 1, 1, NONE, 0)[0] == STATUS["PICO_INVALID_PARAMETER"]


def test_get_values_argument_validation() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _capture(fake, handle)
    g = fake.ps2000aGetValues
    assert g(handle, 0, 10, 1, NONE, 1)[0] == STATUS["PICO_SEGMENT_OUT_OF_RANGE"]
    assert g(handle, 0, 10, 1, "RATIO", 0)[0] == STATUS["PICO_INVALID_PARAMETER"]
    assert (
        g(handle, 0, 10, 1, "PS2000A_RATIO_MODE_AVERAGE", 0)[0]
        == STATUS["PICO_RATIO_MODE_NOT_SUPPORTED"]
    )
    assert g(handle, 0, 10, 12345, NONE, 0)[0] == OK  # ratio ignored with MODE_NONE (PG §3.18)


def test_get_values_buffer_too_short() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _channel(fake, handle, A)
    short = np.zeros(10, dtype=np.int16)
    fake.ps2000aSetDataBuffer(handle, A, short, 0, NONE)
    fake.ps2000aRunBlock(handle, 0, 100, 3, 0, 0)
    while fake.ps2000aIsReady(handle)[1] == 0:
        pass
    assert fake.ps2000aGetValues(handle, 0, 100, 1, NONE, 0)[0] == STATUS["PICO_INVALID_PARAMETER"]
    assert fake.ps2000aGetValues(handle, 0, 10, 1, NONE, 0)[0] == OK


def test_buffer_may_be_registered_after_ready() -> None:
    # PG §2.6.1.1 step 7 comes after the wait for ready
    fake = FakePs2000a()
    handle = _open(fake)
    _channel(fake, handle, A)
    fake.ps2000aRunBlock(handle, 0, 100, 3, 0, 0)
    while fake.ps2000aIsReady(handle)[1] == 0:
        pass
    buf = np.zeros(100, dtype=np.int16)
    assert fake.ps2000aSetDataBuffer(handle, A, buf, 0, NONE) == (OK,)
    assert fake.ps2000aGetValues(handle, 0, 100, 1, NONE, 0)[:2] == (OK, 100)
    assert buf.any()


def test_channels_without_buffer_and_disabled_channels_are_left_alone() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _channel(fake, handle, A)
    _channel(fake, handle, B, enabled=0)
    buf_b = np.full(100, 77, dtype=np.int16)
    fake.ps2000aSetDataBuffer(handle, B, buf_b, 0, NONE)  # disabled channel's buffer
    fake.ps2000aRunBlock(handle, 0, 100, 3, 0, 0)  # enabled channel A has no buffer
    while fake.ps2000aIsReady(handle)[1] == 0:
        pass
    assert fake.ps2000aGetValues(handle, 0, 100, 1, NONE, 0) == (OK, 100, 0)
    assert (buf_b == 77).all()


# --- generated clock ---------------------------------------------------------------------


@pytest.mark.parametrize("interval_s", [1e-6, 2e-6])
def test_clock_period_and_amplitude(interval_s: float) -> None:
    fake = FakePs2000a(clock_hz=1000.0, clock_v=1.0)
    handle = _open(fake)
    buffers = _capture(
        fake, handle, pre=100, post=3900, interval_s=interval_s, ranges=("PS2000A_2V",)
    )
    assert _get(fake, handle, 4000) == (OK, 4000, 0)
    raw = buffers[A]
    # the clock is a square wave between 0 and clock_v: counts 0 and 1 V / 2 V * 32512
    assert set(np.unique(raw)) == {0, 16256}
    edges = _rising_edges(raw)
    period_samples = round(1e-3 / interval_s)  # 1000 samples at 1 us, 500 at 2 us
    assert len(edges) >= 3
    assert np.all(np.diff(edges) == period_samples)
    # half the period is high
    assert (raw[edges[0] : edges[0] + period_samples] > 0).sum() == period_samples // 2


def test_clock_amplitude_follows_clock_v_and_range() -> None:
    fake = FakePs2000a(clock_v=0.25)
    handle = _open(fake)
    buffers = _capture(fake, handle, ranges=("PS2000A_500MV",))
    _get(fake, handle)
    assert buffers[A].max() == round(0.25 / 0.5 * 32512)
    assert buffers[A].min() == 0


def test_clock_frequency_follows_clock_hz() -> None:
    fake = FakePs2000a(clock_hz=2500.0)
    handle = _open(fake)
    buffers = _capture(fake, handle, post=3900, interval_s=1e-6)
    _get(fake, handle, 4000)
    edges = _rising_edges(buffers[A])
    assert np.all(np.diff(edges) == 400)  # 1 / 2.5 kHz at 1 us


def test_every_enabled_channel_carries_the_clock() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    buffers = _capture(
        fake, handle, channels=(A, B), ranges=("PS2000A_2V", "PS2000A_1V"), interval_s=2e-6
    )
    assert _get(fake, handle) == (OK, 2000, 0)  # one call fills both buffers (PG §3.18)
    assert buffers[A].max() == 16256
    assert buffers[B].max() == 32512
    assert np.array_equal(buffers[A] > 0, buffers[B] > 0)


@pytest.mark.parametrize("interval_s", [1e-6, 2e-6])
def test_no_trigger_phase_is_fixed_at_zero(interval_s: float) -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    buffers = _capture(fake, handle, pre=100, interval_s=interval_s)
    _get(fake, handle)
    raw = buffers[A]
    # rising edge exactly at index pre, so the sample before it is low
    assert raw[99] == 0
    assert raw[100] == 16256


@pytest.mark.parametrize("interval_s", [1e-6, 2e-6])
@pytest.mark.parametrize("pre", [100, 0, 37])
def test_rising_trigger_puts_the_edge_at_index_pre(interval_s: float, pre: int) -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    threshold = 8128  # 0.5 V on the 2 V range
    buffers = _capture(
        fake,
        handle,
        pre=pre,
        post=3000,
        interval_s=interval_s,
        trigger=(A, threshold, "PS2000A_RISING"),
    )
    _get(fake, handle, pre + 3000)
    raw = buffers[A]
    assert raw[pre] >= threshold  # first sample at or above the threshold ...
    if pre > 0:
        assert raw[pre - 1] < threshold  # ... after being below it


@pytest.mark.parametrize("interval_s", [1e-6, 2e-6])
@pytest.mark.parametrize("pre", [100, 0, 37])
def test_falling_trigger_puts_the_edge_at_index_pre(interval_s: float, pre: int) -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    threshold = 8128
    buffers = _capture(
        fake,
        handle,
        pre=pre,
        post=3000,
        interval_s=interval_s,
        trigger=(A, threshold, "PS2000A_FALLING"),
    )
    _get(fake, handle, pre + 3000)
    raw = buffers[A]
    assert raw[pre] <= threshold  # first sample at or below the threshold ...
    if pre > 0:
        assert raw[pre - 1] > threshold  # ... after being above it


def test_trigger_on_the_second_channel_uses_that_channels_range() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    # 0.5 V on B's 1 V range is 16256 counts, 0.25 V on A's 2 V range would be 4064
    buffers = _capture(
        fake,
        handle,
        channels=(A, B),
        ranges=("PS2000A_2V", "PS2000A_1V"),
        trigger=(B, 16256, "PS2000A_RISING"),
    )
    _get(fake, handle)
    assert buffers[B][99] < 16256 <= buffers[B][100]
    assert buffers[A][99] < buffers[A][100]


def test_other_directions_have_a_defined_alignment() -> None:
    for direction, first_high in (
        ("PS2000A_ABOVE", True),
        ("PS2000A_RISING_OR_FALLING", True),
        ("PS2000A_BELOW", False),
    ):
        fake = FakePs2000a()
        handle = _open(fake)
        buffers = _capture(fake, handle, trigger=(A, 8128, direction))
        _get(fake, handle)
        assert bool(buffers[A][100] > 0) is first_high, direction


def test_trigger_that_never_fires_behaves_as_auto_trigger() -> None:
    fake = FakePs2000a(clock_v=1.0)
    handle = _open(fake)
    # 1.5 V on the 2 V range is above the 1 V clock: no crossing, phase 0 like no trigger
    threshold = round(1.5 / 2.0 * 32512)
    buffers = _capture(fake, handle, trigger=(A, threshold, "PS2000A_FALLING"))
    _get(fake, handle)
    assert buffers[A][99] == 0
    assert buffers[A][100] == 16256


def test_disabled_trigger_after_enabled_one_resets_alignment() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _channel(fake, handle, A)
    assert fake.ps2000aSetSimpleTrigger(handle, 1, A, 8128, "PS2000A_FALLING", 0, 0) == (OK,)
    assert fake.ps2000aSetSimpleTrigger(handle, 0, A, 0, "PS2000A_RISING", 0, 0) == (OK,)
    buf = np.zeros(2000, dtype=np.int16)
    fake.ps2000aSetDataBuffer(handle, A, buf, 0, NONE)
    fake.ps2000aRunBlock(handle, 100, 1900, 129, 0, 0)  # 1 us
    while fake.ps2000aIsReady(handle)[1] == 0:
        pass
    _get(fake, handle)
    assert buf[99] == 0
    assert buf[100] == 16256


def test_ramp_signal() -> None:
    fake = FakePs2000a(signal="ramp", clock_v=1.0)
    handle = _open(fake)
    buffers = _capture(fake, handle, pre=0, post=2500, ranges=("PS2000A_1V",))
    _get(fake, handle, 2500)
    expected = np.rint((np.arange(2500) % 1000) / 1000 * 32512).astype(np.int16)
    assert np.array_equal(buffers[A], expected)


# --- clipping and the overflow bits ------------------------------------------------------


def test_clipping_sets_overflow_bit_for_channel_a() -> None:
    fake = FakePs2000a(clock_v=1.0)
    handle = _open(fake)
    buffers = _capture(fake, handle, ranges=("PS2000A_500MV",))
    status, n, overflow = _get(fake, handle)
    assert (status, n, overflow) == (OK, 2000, 0b01)  # PG §3.18: bit 0 = channel A
    assert buffers[A].max() == 32512  # clipped to full scale
    assert buffers[A].min() == 0


def test_clipping_sets_overflow_bit_per_channel() -> None:
    fake = FakePs2000a(clock_v=1.0)
    handle = _open(fake)
    # A fits (2 V range), B clips (500 mV range)
    buffers = _capture(fake, handle, channels=(A, B), ranges=("PS2000A_2V", "PS2000A_500MV"))
    assert _get(fake, handle)[2] == 0b10
    assert buffers[B].max() == 32512
    assert buffers[A].max() == 16256
    # both clip
    fake2 = FakePs2000a(clock_v=1.0)
    h2 = _open(fake2)
    _capture(fake2, h2, channels=(A, B), ranges=("PS2000A_500MV", "PS2000A_200MV"))
    assert _get(fake2, h2)[2] == 0b11


def test_exact_full_scale_is_not_an_overflow() -> None:
    fake = FakePs2000a(clock_v=1.0)
    handle = _open(fake)
    buffers = _capture(fake, handle, ranges=("PS2000A_1V",))
    assert _get(fake, handle) == (OK, 2000, 0)
    assert buffers[A].max() == 32512


def test_overflow_only_counts_returned_samples() -> None:
    fake = FakePs2000a(signal="ramp", clock_v=2.0)
    handle = _open(fake)
    buffers = _capture(fake, handle, pre=0, post=1000, ranges=("PS2000A_1V",))
    # ramp reaches 2 V only near the end; the first 400 samples stay below 0.8 V
    assert fake.ps2000aGetValues(handle, 0, 400, 1, NONE, 0) == (OK, 400, 0)
    assert fake.ps2000aGetValues(handle, 0, 1000, 1, NONE, 0)[2] == 0b01
    assert buffers[A][:400].max() < 32512


# --- defects -----------------------------------------------------------------------------


def _clean_and_defective(defect: str | None) -> Int16Array:
    fake = FakePs2000a(defect=defect)  # type: ignore[arg-type]
    handle = _open(fake)
    buffers = _capture(fake, handle, ranges=("PS2000A_2V",))
    assert _get(fake, handle) == (OK, 2000, 0)
    return buffers[A]


def test_defect_shift_adds_ten_percent_dc() -> None:
    raw = _clean_and_defective("shift")
    assert set(np.unique(raw)) == {round(0.1 / 2 * 32512), round(1.1 / 2 * 32512)}


def test_defect_gain_multiplies_by_1_1() -> None:
    raw = _clean_and_defective("gain")
    assert set(np.unique(raw)) == {0, round(1.1 / 2 * 32512)}


def test_defect_glitch_replaces_one_sample_at_pre_plus_7() -> None:
    clean = _clean_and_defective(None)
    raw = _clean_and_defective("glitch")
    changed = np.flatnonzero(raw != clean)
    assert changed.tolist() == [107]
    assert raw[107] == 32512


def test_defect_glitch_beyond_the_block_is_skipped() -> None:
    fake = FakePs2000a(defect="glitch")
    handle = _open(fake)
    buffers = _capture(fake, handle, pre=0, post=5)
    assert _get(fake, handle, 5) == (OK, 5, 0)
    assert buffers[A].max() <= 16256


def test_defects_with_ramp() -> None:
    fake = FakePs2000a(signal="ramp", defect="gain", clock_v=1.0)
    handle = _open(fake)
    buffers = _capture(fake, handle, pre=0, post=1000, ranges=("PS2000A_2V",))
    _get(fake, handle, 1000)
    expected = np.rint(np.arange(1000) / 1000 * 1.1 / 2 * 32512).astype(np.int16)
    assert np.array_equal(buffers[A], expected)


# --- data written in place, Stop keeps data ----------------------------------------------


def test_data_is_written_into_the_registered_array_in_place() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _channel(fake, handle, A)
    buf = np.zeros(2000, dtype=np.int16)
    address = buf.ctypes.data
    fake.ps2000aSetDataBuffer(handle, A, buf, 0, NONE)
    fake.ps2000aSetSimpleTrigger(handle, 0, A, 0, "PS2000A_RISING", 0, 0)
    fake.ps2000aRunBlock(handle, 100, 1900, 129, 0, 0)
    while fake.ps2000aIsReady(handle)[1] == 0:
        pass
    view = buf[:]  # a view stays valid only if the fake writes in place
    assert not buf.any()
    assert _get(fake, handle)[:2] == (OK, 2000)
    assert buf.ctypes.data == address
    assert view.any()
    assert view[100] == 16256
    assert fake.units[handle].buffers[A] is buf


def test_only_the_returned_samples_are_written() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    _channel(fake, handle, A)
    buf = np.full(100, -5, dtype=np.int16)
    fake.ps2000aSetDataBuffer(handle, A, buf, 0, NONE)
    fake.ps2000aRunBlock(handle, 0, 50, 3, 0, 0)
    while fake.ps2000aIsReady(handle)[1] == 0:
        pass
    assert fake.ps2000aGetValues(handle, 0, 100, 1, NONE, 0)[1] == 50
    assert (buf[50:] == -5).all()


def test_stop_keeps_the_data() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    buffers = _capture(fake, handle)
    assert fake.ps2000aStop(handle) == (OK,)
    assert not fake.units[handle].armed
    assert _get(fake, handle)[:2] == (OK, 2000)  # PG §2.6.1 "Data retention"
    assert buffers[A].max() == 16256
    assert fake.ps2000aIsReady(handle) == (OK, 0)  # nothing running any more
    assert fake.ps2000aStop(handle) == (OK,)  # idempotent


def test_stop_before_ready_leaves_no_samples() -> None:
    fake = FakePs2000a(ready_after=3)
    handle = _open(fake)
    _capture(fake, handle, poll=False)
    assert fake.ps2000aStop(handle) == (OK,)
    assert _get(fake, handle)[0] == STATUS["PICO_NO_SAMPLES_AVAILABLE"]


def test_new_run_after_stop() -> None:
    fake = FakePs2000a(ready_after=1)
    handle = _open(fake)
    _capture(fake, handle)
    fake.ps2000aStop(handle)
    assert fake.ps2000aRunBlock(handle, 100, 1900, 129, 0, 0)[0] == OK
    assert fake.units[handle].armed
    assert _get(fake, handle)[0] == STATUS["PICO_NO_SAMPLES_AVAILABLE"]  # countdown restarted


def test_settings_changed_after_run_do_not_alter_the_running_capture() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    buffers = _capture(fake, handle, ranges=("PS2000A_2V",))
    _channel(fake, handle, A, "PS2000A_20MV")
    _get(fake, handle)
    assert buffers[A].max() == 16256


# --- reject, log -------------------------------------------------------------------------


def test_every_call_is_logged_with_its_arguments_in_order() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    buf = np.zeros(4, dtype=np.int16)
    fake.ps2000aSetChannel(handle, A, 1, "PS2000A_DC", "PS2000A_1V", 0.0)
    fake.ps2000aSetDataBuffer(handle, A, buf, 0, NONE)
    fake.ps2000aStop(handle)
    names = [name for name, _ in fake.log]
    assert names == [
        "ps2000aOpenUnit",
        "ps2000aSetChannel",
        "ps2000aSetDataBuffer",
        "ps2000aStop",
    ]
    assert fake.log[0] == ("ps2000aOpenUnit", (None,))
    assert fake.log[1] == ("ps2000aSetChannel", (handle, A, 1, "PS2000A_DC", "PS2000A_1V", 0.0))
    assert fake.log[2][1][2] is buf
    assert fake.log[3] == ("ps2000aStop", (handle,))


def test_failed_calls_are_logged_too() -> None:
    fake = FakePs2000a()
    fake.ps2000aCloseUnit(5)
    assert fake.log == [("ps2000aCloseUnit", (5,))]


def test_reject_returns_the_requested_status_and_logs() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    fake.reject["ps2000aSetChannel"] = "PICO_NOT_RESPONDING"
    result = fake.ps2000aSetChannel(handle, A, 1, "PS2000A_DC", "PS2000A_1V", 0.0)
    assert result == (STATUS["PICO_NOT_RESPONDING"],)
    assert fake.log[-1][0] == "ps2000aSetChannel"
    assert not fake.units[handle].channels[A].enabled  # the call did not take effect
    # sticky until the test clears it
    assert fake.ps2000aSetChannel(handle, A, 1, "PS2000A_DC", "PS2000A_1V", 0.0) == result
    del fake.reject["ps2000aSetChannel"]
    assert fake.ps2000aSetChannel(handle, A, 1, "PS2000A_DC", "PS2000A_1V", 0.0) == (OK,)
    assert fake.units[handle].channels[A].enabled


def test_reject_wins_over_handle_check_and_pads_out_arguments() -> None:
    fake = FakePs2000a()
    fake.reject = {
        "ps2000aEnumerateUnits": "PICO_BUSY",
        "ps2000aOpenUnit": "PICO_NOT_FOUND",
        "ps2000aGetUnitInfo": "PICO_INFO_UNAVAILABLE",
        "ps2000aMaximumValue": "PICO_INVALID_HANDLE",
        "ps2000aGetTimebase2": "PICO_INVALID_TIMEBASE",
        "ps2000aRunBlock": "PICO_TOO_MANY_SAMPLES",
        "ps2000aIsReady": "PICO_NO_SAMPLES_AVAILABLE",
        "ps2000aGetValues": "PICO_NO_SAMPLES_AVAILABLE",
        "ps2000aStop": "PICO_DRIVER_FUNCTION",
        "ps2000aCloseUnit": "PICO_DRIVER_FUNCTION",
    }
    assert fake.ps2000aEnumerateUnits() == (STATUS["PICO_BUSY"], 0, "")
    assert fake.ps2000aOpenUnit(None) == (STATUS["PICO_NOT_FOUND"], 0)
    assert fake.units == {}  # nothing was opened
    assert fake.ps2000aGetUnitInfo(1, "PICO_VARIANT_INFO") == (STATUS["PICO_INFO_UNAVAILABLE"], "")
    assert fake.ps2000aMaximumValue(77) == (STATUS["PICO_INVALID_HANDLE"], 0)
    assert fake.ps2000aGetTimebase2(1, 3, 10, 0, 0) == (STATUS["PICO_INVALID_TIMEBASE"], 0.0, 0)
    assert fake.ps2000aRunBlock(1, 0, 10, 3, 0, 0) == (STATUS["PICO_TOO_MANY_SAMPLES"], 0)
    assert fake.ps2000aIsReady(1) == (STATUS["PICO_NO_SAMPLES_AVAILABLE"], 0)
    assert fake.ps2000aGetValues(1, 0, 10, 1, NONE, 0) == (
        STATUS["PICO_NO_SAMPLES_AVAILABLE"],
        0,
        0,
    )
    assert fake.ps2000aStop(1) == (STATUS["PICO_DRIVER_FUNCTION"],)
    assert fake.ps2000aCloseUnit(1) == (STATUS["PICO_DRIVER_FUNCTION"],)
    assert len(fake.log) == 10


def test_reject_with_unknown_status_name_is_a_key_error() -> None:
    fake = FakePs2000a()
    fake.reject["ps2000aStop"] = "PICO_NOT_A_STATUS"
    with pytest.raises(KeyError):
        fake.ps2000aStop(1)


def test_reject_on_stop_and_close_does_not_close_the_unit() -> None:
    fake = FakePs2000a()
    handle = _open(fake)
    fake.reject["ps2000aCloseUnit"] = "PICO_DRIVER_FUNCTION"
    assert fake.ps2000aCloseUnit(handle) == (STATUS["PICO_DRIVER_FUNCTION"],)
    assert handle in fake.units
    assert fake.closed_handles == []
