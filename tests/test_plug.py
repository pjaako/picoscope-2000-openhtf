"""Tests for the plug. No hardware, no sleeps, no network: the driver is a `FakePs2000a`, and
`plug.time` is replaced by a fake clock so that polling never waits.
"""

import logging
from collections.abc import Iterator
from typing import Any

import numpy as np
import openhtf as htf
import pytest

from picoscope_2000_openhtf import (
    Capture,
    CaptureError,
    Channel,
    ClippedError,
    Edge,
    PicoError,
    PicoScope2000Plug,
    Waveform,
    WaveformMeta,
    measure,
    waveform_from_raw,
)
from picoscope_2000_openhtf import plug as plug_module
from picoscope_2000_openhtf.fake_resource import STATUS, FakePs2000a
from picoscope_2000_openhtf.plug import CONF
from picoscope_2000_openhtf.units import V, us

A, B, C, D = "PS2000A_CHANNEL_A", "PS2000A_CHANNEL_B", "PS2000A_CHANNEL_C", "PS2000A_CHANNEL_D"
NONE = "PS2000A_RATIO_MODE_NONE"

CAPTURE = Capture(
    channels=(Channel(ch=1, range=2 * V), Channel(ch=2, range=2 * V)),
    sample_interval=1 * us,
    pre_samples=100,
    post_samples=1900,
    trigger=Edge(source=1, level=0.5 * V, auto_ms=1000),
)


class _Clock:
    """Fake `time` module: `sleep` advances `monotonic`, nothing ever waits."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Clock]:
    fake_clock = _Clock()
    monkeypatch.setattr(plug_module, "time", fake_clock)
    yield fake_clock
    assert sum(fake_clock.sleeps) < 60  # polling stayed on the fake clock


@pytest.fixture(autouse=True)
def _reset_conf() -> Iterator[None]:
    CONF.reset()
    yield
    CONF.reset()


def _plug(
    serial: str | None = None, timeout_s: float | None = None, **fake_kwargs: Any
) -> tuple[PicoScope2000Plug, FakePs2000a]:
    """A plug on a fresh fake; the fake's log is cleared after the constructor."""
    fake = FakePs2000a(**fake_kwargs)
    plug = PicoScope2000Plug(serial, api=fake, timeout_s=timeout_s)
    fake.log.clear()
    return plug, fake


def _calls(fake: FakePs2000a) -> list[tuple[str, tuple[object, ...]]]:
    """The fake's log with numpy buffers replaced by `("buffer", dtype, size)`."""
    return [
        (
            name,
            tuple(
                ("buffer", str(a.dtype), a.size) if isinstance(a, np.ndarray) else a for a in args
            ),
        )
        for name, args in fake.log
    ]


def _buffer(size: int) -> tuple[str, str, int]:
    """How `_calls` shows an int16 buffer of `size` samples."""
    return ("buffer", "int16", size)


def _names(fake: FakePs2000a) -> list[str]:
    return [name for name, _ in fake.log]


def _acquire(plug: PicoScope2000Plug, capture: Capture = CAPTURE, *, poll_s: float = 0.01) -> None:
    plug.apply_capture(capture)
    plug.single()
    plug.wait_ready(poll_s=poll_s)


def _single_channel(
    interval: float = 1 * us, range_v: float = 2 * V, pre: int = 100, post: int = 4900
) -> Capture:
    return Capture(
        channels=(Channel(ch=1, range=range_v),),
        sample_interval=interval,
        pre_samples=pre,
        post_samples=post,
        trigger=Edge(source=1, level=0.5 * V, auto_ms=1000),
    )


def test_package_exports_resolve() -> None:
    import picoscope_2000_openhtf as package

    for name in package.__all__:
        assert getattr(package, name) is not None
    assert package.PicoScope2000Plug is PicoScope2000Plug
    assert package.PicoError is PicoError
    assert package.Waveform is Waveform
    assert package.ClippedError is ClippedError
    assert issubclass(package.CaptureError, RuntimeError)
    assert issubclass(PicoError, RuntimeError)
    assert issubclass(ClippedError, ValueError)
    with pytest.raises(AttributeError):
        package.nope  # noqa: B018


# -- construction -----------------------------------------------------------------------------


def test_constructor_log_sequence() -> None:
    fake = FakePs2000a()
    plug = PicoScope2000Plug(api=fake)
    info_names = [
        "PICO_DRIVER_VERSION",
        "PICO_USB_VERSION",
        "PICO_HARDWARE_VERSION",
        "PICO_VARIANT_INFO",
        "PICO_BATCH_AND_SERIAL",
        "PICO_CAL_DATE",
        "PICO_KERNEL_VERSION",
        "PICO_DIGITAL_HARDWARE_VERSION",
        "PICO_ANALOGUE_HARDWARE_VERSION",
        "PICO_FIRMWARE_VERSION_1",
        "PICO_FIRMWARE_VERSION_2",
    ]
    assert fake.log == [
        ("ps2000aEnumerateUnits", ()),  # PG §3.4
        ("ps2000aOpenUnit", (None,)),  # PG §3.32
        *[("ps2000aGetUnitInfo", (1, name)) for name in info_names],  # PG §3.17
        ("ps2000aMaximumValue", (1,)),  # PG §3.28
        ("ps2000aMinimumValue", (1,)),  # PG §3.30
    ]
    assert list(plug.info) == info_names
    assert plug.serial == "FAKE0/001"
    assert plug.variant == "2207BMSO"
    assert plug.info["PICO_DRIVER_VERSION"] == "0.0.0.0-fake"
    assert (plug.max_adc, plug.min_adc) == (32512, -32512)  # PG §2.3
    assert plug.channel_count == 4
    assert PicoScope2000Plug.auto_placeholder is True


def test_constructor_opens_the_unit_with_the_given_serial() -> None:
    fake = FakePs2000a(serials=("FAKE0/001", "FAKE0/002"))
    plug = PicoScope2000Plug("FAKE0/002", api=fake)
    assert ("ps2000aOpenUnit", ("FAKE0/002",)) in fake.log
    assert plug.serial == "FAKE0/002"


def test_unknown_serial_raises_not_found_and_closes_nothing() -> None:
    fake = FakePs2000a()
    with pytest.raises(PicoError) as excinfo:
        PicoScope2000Plug("NOPE/000", api=fake)
    assert excinfo.value.function == "ps2000aOpenUnit"
    assert excinfo.value.name == "PICO_NOT_FOUND"
    assert "ps2000aCloseUnit" not in _names(fake)


@pytest.mark.parametrize("handle", [0, -1])
def test_ok_status_with_unusable_handle_is_not_found(handle: int) -> None:
    class _NoHandle(FakePs2000a):
        def ps2000aOpenUnit(self, serial: str | None) -> tuple[int, int]:
            super().ps2000aOpenUnit(serial)
            return (STATUS["PICO_OK"], handle)  # PG §3.32: 0 none found, -1 failed to open

    fake = _NoHandle()
    with pytest.raises(PicoError) as excinfo:
        PicoScope2000Plug(api=fake)
    assert excinfo.value.name == "PICO_NOT_FOUND"
    assert excinfo.value.status == STATUS["PICO_NOT_FOUND"]
    assert f"handle {handle}" in str(excinfo.value)
    assert "ps2000aCloseUnit" not in _names(fake)


def test_enumerate_failure_raises_before_opening() -> None:
    fake = FakePs2000a()
    fake.reject["ps2000aEnumerateUnits"] = "PICO_BUSY"
    with pytest.raises(PicoError) as excinfo:
        PicoScope2000Plug(api=fake)
    assert excinfo.value.function == "ps2000aEnumerateUnits"
    assert _names(fake) == ["ps2000aEnumerateUnits"]


def test_info_unavailable_is_stored_as_empty_string() -> None:
    fake = FakePs2000a()
    fake.reject["ps2000aGetUnitInfo"] = "PICO_INFO_UNAVAILABLE"  # PG §3.17 Returns
    plug = PicoScope2000Plug(api=fake)
    assert len(plug.info) == 11
    assert set(plug.info.values()) == {""}
    assert plug.serial == ""


def test_other_info_error_raises_and_closes_the_unit() -> None:
    fake = FakePs2000a()
    fake.reject["ps2000aGetUnitInfo"] = "PICO_INVALID_INFO"
    with pytest.raises(PicoError) as excinfo:
        PicoScope2000Plug(api=fake)
    assert excinfo.value.function == "ps2000aGetUnitInfo"
    assert excinfo.value.name == "PICO_INVALID_INFO"
    assert fake.log[-1] == ("ps2000aCloseUnit", (1,))
    assert fake.closed_handles == [1]


@pytest.mark.parametrize("function", ["ps2000aMaximumValue", "ps2000aMinimumValue"])
def test_adc_limit_failure_closes_the_unit(function: str) -> None:
    fake = FakePs2000a()
    fake.reject[function] = "PICO_NOT_RESPONDING"
    with pytest.raises(PicoError) as excinfo:
        PicoScope2000Plug(api=fake)
    assert excinfo.value.function == function
    assert fake.closed_handles == [1]
    assert fake.units == {}


def test_cleanup_failure_does_not_hide_the_original_error() -> None:
    fake = FakePs2000a()
    fake.reject["ps2000aMaximumValue"] = "PICO_NOT_RESPONDING"
    fake.reject["ps2000aCloseUnit"] = "PICO_BUSY"
    with pytest.raises(PicoError) as excinfo:
        PicoScope2000Plug(api=fake)
    assert excinfo.value.function == "ps2000aMaximumValue"


def test_several_units_and_no_serial_log_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakePs2000a(serials=("FAKE0/001", "FAKE0/002"))
    with caplog.at_level(logging.INFO):
        PicoScope2000Plug(api=fake)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "FAKE0/001,FAKE0/002" in warnings[0].getMessage()
    assert any(
        "found 2 unopened unit(s): FAKE0/001,FAKE0/002" in r.getMessage() for r in caplog.records
    )


def test_no_warning_with_a_serial_or_a_single_unit(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        PicoScope2000Plug("FAKE0/002", api=FakePs2000a(serials=("FAKE0/001", "FAKE0/002")))
        PicoScope2000Plug(api=FakePs2000a())
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert any("opened 2207BMSO serial FAKE0/002" in r.getMessage() for r in caplog.records)


def test_debug_logging_of_calls_and_statuses(caplog: pytest.LogCaptureFixture) -> None:
    plug, _ = _plug()
    with caplog.at_level(logging.DEBUG):
        plug.apply_capture(CAPTURE)
    messages = [r.getMessage() for r in caplog.records]
    assert (
        "-> ps2000aSetChannel(1, 'PS2000A_CHANNEL_A', 1, 'PS2000A_DC', 'PS2000A_2V', 0.0)"
        in messages
    )
    buffer_call = "-> ps2000aSetDataBuffer(1, 'PS2000A_CHANNEL_A', <int16[2000]>, 0, '{}')"
    assert buffer_call.format(NONE) in messages
    assert "<- PICO_OK" in messages
    assert "<- PICO_INVALID_CHANNEL" in messages  # channel C on the two-channel fake


# -- configuration ----------------------------------------------------------------------------


def test_conf_keys_are_declared_with_defaults() -> None:
    assert CONF.picoscope_2000_serial is None
    assert CONF.picoscope_2000_timeout_s == 10.0


def test_serial_precedence_argument_then_conf_then_default() -> None:
    serials = ("FAKE0/001", "FAKE0/002", "FAKE0/003")
    CONF.load(picoscope_2000_serial="FAKE0/002")
    fake = FakePs2000a(serials=serials)
    assert PicoScope2000Plug(api=fake).serial == "FAKE0/002"  # CONF beats the default
    fake = FakePs2000a(serials=serials)
    assert PicoScope2000Plug("FAKE0/003", api=fake).serial == "FAKE0/003"  # argument beats CONF
    CONF.reset()
    fake = FakePs2000a(serials=serials)
    assert PicoScope2000Plug(api=fake).serial == "FAKE0/001"  # default: first unit found


def test_timeout_precedence_argument_then_conf_then_default() -> None:
    def timeout_message(plug: PicoScope2000Plug, fake: FakePs2000a) -> str:
        fake.ready_after = 10**9
        plug.apply_capture(_single_channel())
        plug.single()
        with pytest.raises(TimeoutError) as excinfo:
            plug.wait_ready(poll_s=1.0)
        return str(excinfo.value)

    plug, fake = _plug()
    assert timeout_message(plug, fake) == "no trigger within 10 s"
    CONF.load(picoscope_2000_timeout_s=3.0)
    plug, fake = _plug()
    assert timeout_message(plug, fake) == "no trigger within 3 s"
    plug, fake = _plug(timeout_s=2.5)
    assert timeout_message(plug, fake) == "no trigger within 2.5 s"


# -- list_units -------------------------------------------------------------------------------


def test_list_units_splits_the_serials() -> None:
    fake = FakePs2000a(serials=("AQ005/139", "VDR61/356"))
    assert PicoScope2000Plug.list_units(fake) == ["AQ005/139", "VDR61/356"]
    assert fake.log == [("ps2000aEnumerateUnits", ())]


def test_list_units_lists_only_unopened_units_and_may_be_empty() -> None:
    fake = FakePs2000a(serials=("AQ005/139", "VDR61/356"))
    PicoScope2000Plug("AQ005/139", api=fake)
    assert PicoScope2000Plug.list_units(fake) == ["VDR61/356"]  # PG §3.4: unopened units only
    assert PicoScope2000Plug.list_units(FakePs2000a(serials=())) == []


def test_list_units_raises_on_a_driver_error() -> None:
    fake = FakePs2000a()
    fake.reject["ps2000aEnumerateUnits"] = "PICO_BUSY"
    with pytest.raises(PicoError, match="ps2000aEnumerateUnits returned PICO_BUSY"):
        PicoScope2000Plug.list_units(fake)


# -- apply_capture ----------------------------------------------------------------------------


def test_apply_capture_log_sequence_two_channel_unit() -> None:
    plug, fake = _plug()
    plug.apply_capture(CAPTURE)
    assert _calls(fake) == [
        ("ps2000aSetChannel", (1, A, 1, "PS2000A_DC", "PS2000A_2V", 0.0)),  # PG §3.39
        ("ps2000aSetChannel", (1, B, 1, "PS2000A_DC", "PS2000A_2V", 0.0)),
        (
            "ps2000aSetChannel",
            (1, C, 0, "PS2000A_DC", "PS2000A_1V", 0.0),
        ),  # tolerated, open question 21
        ("ps2000aSetChannel", (1, D, 0, "PS2000A_DC", "PS2000A_1V", 0.0)),
        ("ps2000aGetTimebase2", (1, 127, 2000, 0, 0)),  # PG §2.7: (127 - 2) / 125 MS/s = 1 us
        ("ps2000aGetTimebase2", (1, 126, 2000, 0, 0)),  # 0.992 us: too short, 127 it is
        ("ps2000aSetSimpleTrigger", (1, 1, A, 8128, "PS2000A_RISING", 0, 1000)),  # 0.5 / 2 * 32512
        ("ps2000aSetDataBuffer", (1, A, _buffer(2000), 0, NONE)),
        ("ps2000aSetDataBuffer", (1, B, _buffer(2000), 0, NONE)),
    ]
    assert plug.channel_count == 2
    assert plug.capture is CAPTURE
    assert plug.timebase == 127
    assert plug.sample_interval_s == pytest.approx(1e-6, rel=1e-6)
    assert plug.max_samples == 32768  # two channels share the memory, PG §2.6.1


def test_apply_capture_registers_zeroed_buffers_in_place() -> None:
    plug, fake = _plug()
    plug.apply_capture(CAPTURE)
    registered = [
        a
        for name, args in fake.log
        if name == "ps2000aSetDataBuffer"
        for a in args
        if isinstance(a, np.ndarray)
    ]
    assert [len(b) for b in registered] == [2000, 2000]
    assert all(b.dtype == np.int16 and not b.any() for b in registered)
    assert registered[0] is not registered[1]


def test_apply_capture_trigger_options_and_no_trigger() -> None:
    plug, fake = _plug()
    capture = Capture(
        channels=(Channel(ch=1, range=2 * V), Channel(ch=2, range=500e-3, coupling="AC")),
        sample_interval=1 * us,
        pre_samples=10,
        post_samples=90,
        trigger=Edge(source=2, level=-0.25, direction="FALLING", auto_ms=0, delay_samples=5),
    )
    plug.apply_capture(capture)
    calls = _calls(fake)
    assert ("ps2000aSetChannel", (1, B, 1, "PS2000A_AC", "PS2000A_500MV", 0.0)) in calls
    assert ("ps2000aSetSimpleTrigger", (1, 1, B, -16256, "PS2000A_FALLING", 5, 0)) in calls
    fake.log.clear()
    plug.apply_capture(
        Capture(
            channels=(Channel(ch=1, range=2 * V),),
            sample_interval=1 * us,
            pre_samples=0,
            post_samples=100,
        )
    )
    assert ("ps2000aSetSimpleTrigger", (1, 0, A, 0, "PS2000A_RISING", 0, 0)) in _calls(
        fake
    )  # PG §3.56


def test_apply_capture_four_channel_unit_has_no_tolerated_error() -> None:
    plug, fake = _plug(variant="2408B")
    plug.apply_capture(_single_channel())
    set_channels = [args for name, args in fake.log if name == "ps2000aSetChannel"]
    assert [args[1] for args in set_channels] == [A, B, C, D]
    assert [args[2] for args in set_channels] == [1, 0, 0, 0]
    assert plug.channel_count == 4
    assert plug.max_samples == 65536


def test_two_channel_unit_by_default_and_all_four_channels_are_sent() -> None:
    plug, fake = _plug()
    assert plug.channel_count == 4  # until the unit says otherwise
    plug.apply_capture(CAPTURE)
    assert plug.channel_count == 2
    assert [args[1] for name, args in fake.log if name == "ps2000aSetChannel"] == [A, B, C, D]


def test_enabled_channel_the_unit_does_not_have_raises() -> None:
    plug, fake = _plug()
    capture = Capture(
        channels=(Channel(ch=1, range=2 * V), Channel(ch=3, range=2 * V)),
        sample_interval=1 * us,
        pre_samples=0,
        post_samples=100,
    )
    with pytest.raises(PicoError) as excinfo:
        plug.apply_capture(capture)
    assert excinfo.value.function == "ps2000aSetChannel"
    assert excinfo.value.name == "PICO_INVALID_CHANNEL"
    assert _names(fake) == ["ps2000aSetChannel"] * 3  # stops at the first failure
    assert plug.capture is None
    with pytest.raises(RuntimeError, match="apply_capture"):
        plug.single()


def test_other_set_channel_errors_for_a_disabled_channel_raise() -> None:
    plug, fake = _plug(variant="2408B")
    fake.reject["ps2000aSetChannel"] = "PICO_INVALID_VOLTAGE_RANGE"
    with pytest.raises(PicoError) as excinfo:
        plug.apply_capture(CAPTURE)
    assert excinfo.value.name == "PICO_INVALID_VOLTAGE_RANGE"
    assert _names(fake) == ["ps2000aSetChannel"]  # the enabled channel A fails first


def test_invalid_channel_for_channel_a_or_b_is_not_tolerated() -> None:
    plug, fake = _plug()
    fake.reject["ps2000aSetChannel"] = "PICO_INVALID_CHANNEL"
    with pytest.raises(PicoError, match="PICO_INVALID_CHANNEL"):
        plug.apply_capture(CAPTURE)
    assert plug.channel_count == 4
    assert _names(fake) == ["ps2000aSetChannel"]  # enabled channel A fails first, no tolerance


@pytest.mark.parametrize(
    ("interval", "expected_timebases", "accepted", "accepted_ns"),
    [
        (1 * us, [127, 126], 127, 1000.0),  # exact estimate, then the check below it
        (1.5 * us, [190, 189], 190, 1504.0),  # 189 is 1.496 us, too short
        (1.5045 * us, [190, 191], 191, 1512.0),  # estimate too small: walk up, 190 is known
        (8e-9, [3, 2], 3, 8.0),  # PG §2.7: n = 3 is 8 ns
        (4e-9, [2, 1], 2, 4.0),  # PG §2.7: n = 2 is 4 ns, n = 1 (2 ns) is too short
        (3e-9, [2, 1], 2, 4.0),  # between two entries: the next longer interval
    ],
)
def test_timebase_search_on_the_1gs_table(
    interval: float, expected_timebases: list[int], accepted: int, accepted_ns: float
) -> None:
    plug, fake = _plug()
    capture = Capture(
        channels=(Channel(ch=1, range=2 * V), Channel(ch=2, range=2 * V)),
        sample_interval=interval,
        pre_samples=10,
        post_samples=90,
    )
    plug.apply_capture(capture)
    searched = [args[1] for name, args in fake.log if name == "ps2000aGetTimebase2"]
    assert searched == expected_timebases
    assert plug.timebase == accepted
    assert plug.sample_interval_s == pytest.approx(accepted_ns * 1e-9, rel=1e-6)


def test_timebase_zero_is_skipped_with_two_channels() -> None:
    plug, fake = _plug()
    plug.apply_capture(
        Capture(
            channels=(Channel(ch=1, range=2 * V), Channel(ch=2, range=2 * V)),
            sample_interval=1e-9,
            pre_samples=10,
            post_samples=90,
        )
    )
    # PG §2.7 footnote: timebase 0 (1 ns) is single-channel only, the fake says INVALID_TIMEBASE
    searched = [args[1] for name, args in fake.log if name == "ps2000aGetTimebase2"]
    assert searched == [0, 1]
    assert plug.timebase == 1
    assert plug.sample_interval_s == pytest.approx(2e-9, rel=1e-6)


def test_timebase_zero_is_used_with_one_channel() -> None:
    plug, fake = _plug()
    plug.apply_capture(_single_channel(interval=1e-9, pre=10, post=90))
    searched = [args[1] for name, args in fake.log if name == "ps2000aGetTimebase2"]
    assert searched == [0]
    assert plug.timebase == 0
    assert plug.sample_interval_s == pytest.approx(1e-9, rel=1e-6)


def test_timebase_search_walks_down_on_a_500_ms_model() -> None:
    plug, fake = _plug(max_rate_hz=5e8)  # PG §2.7: (n - 2) / 62.5 MS/s, 16 ns per step
    plug.apply_capture(_single_channel(interval=0.5 * us, pre=10, post=90))
    searched = [args[1] for name, args in fake.log if name == "ps2000aGetTimebase2"]
    assert searched == list(range(64, 32, -1))  # 64 .. 33, stops at 33: 31 * 16 ns < 500 ns
    assert plug.timebase == 34
    assert plug.sample_interval_s == pytest.approx(512e-9, rel=1e-6)


def test_timebase_search_is_capped_at_64_calls() -> None:
    plug, fake = _plug(max_rate_hz=5e8)  # estimate 252, answer 127: 125 steps down
    with pytest.raises(CaptureError, match="64 ps2000aGetTimebase2 calls"):
        plug.apply_capture(_single_channel(interval=2 * us, pre=10, post=90))
    assert _names(fake).count("ps2000aGetTimebase2") == 64
    assert "ps2000aSetSimpleTrigger" not in _names(fake)


def test_timebase_error_after_the_estimate_raises() -> None:
    plug, fake = _plug()
    fake.reject["ps2000aGetTimebase2"] = "PICO_INVALID_HANDLE"
    with pytest.raises(PicoError) as excinfo:
        plug.apply_capture(_single_channel())
    assert excinfo.value.function == "ps2000aGetTimebase2"
    assert excinfo.value.name == "PICO_INVALID_HANDLE"
    searched = [args[1] for name, args in fake.log if name == "ps2000aGetTimebase2"]
    assert searched == [127, 128]  # the estimate is tolerated once, the next failure raises


def test_too_many_samples_raises_capture_error_naming_both_numbers() -> None:
    plug, fake = _plug()
    capture = Capture(
        channels=(Channel(ch=1, range=2 * V), Channel(ch=2, range=2 * V)),
        sample_interval=1 * us,
        pre_samples=1000,
        post_samples=39000,
    )
    with pytest.raises(CaptureError) as excinfo:
        plug.apply_capture(capture)
    assert "40000" in str(excinfo.value)
    assert "32768" in str(excinfo.value)
    assert "ps2000aSetSimpleTrigger" not in _names(fake)
    assert "ps2000aSetDataBuffer" not in _names(fake)
    assert plug.capture is None


def test_failing_trigger_and_buffer_calls_raise_pico_error() -> None:
    plug, fake = _plug()
    fake.reject["ps2000aSetSimpleTrigger"] = "PICO_INVALID_PARAMETER"
    with pytest.raises(PicoError) as excinfo:
        plug.apply_capture(CAPTURE)
    assert excinfo.value.function == "ps2000aSetSimpleTrigger"
    assert "ps2000aSetDataBuffer" not in _names(fake)
    fake.reject.clear()
    fake.reject["ps2000aSetDataBuffer"] = "PICO_INVALID_PARAMETER"
    with pytest.raises(PicoError) as excinfo:
        plug.apply_capture(CAPTURE)
    assert excinfo.value.function == "ps2000aSetDataBuffer"
    assert plug.capture is None


def test_apply_capture_invalidates_cached_waveforms_and_arming() -> None:
    plug, _ = _plug()
    _acquire(plug)
    plug.read_waveform(1)
    plug.apply_capture(CAPTURE)
    with pytest.raises(RuntimeError, match="single"):
        plug.read_waveform(1)


# -- single, wait_ready, read_waveform, stop --------------------------------------------------


def test_single_log_sequence_and_time_indisposed() -> None:
    plug, fake = _plug()
    plug.apply_capture(CAPTURE)
    fake.log.clear()
    plug.single()
    assert fake.log == [("ps2000aRunBlock", (1, 100, 1900, 127, 0, 0))]  # PG §3.37
    assert plug.time_indisposed_ms == 2  # 2000 samples of 1 us, rounded up to ms by the fake


def test_single_before_apply_capture_raises() -> None:
    plug, fake = _plug()
    with pytest.raises(RuntimeError, match="apply_capture"):
        plug.single()
    assert fake.log == []


def test_single_error_raises_pico_error() -> None:
    plug, fake = _plug()
    plug.apply_capture(CAPTURE)
    fake.reject["ps2000aRunBlock"] = "PICO_BUSY"
    with pytest.raises(PicoError) as excinfo:
        plug.single()
    assert excinfo.value.function == "ps2000aRunBlock"
    assert excinfo.value.status == STATUS["PICO_BUSY"]
    assert excinfo.value.name == "PICO_BUSY"
    assert str(excinfo.value) == "ps2000aRunBlock returned PICO_BUSY (0x00000027)"
    with pytest.raises(RuntimeError, match="single"):
        plug.wait_ready()  # nothing is armed


def test_wait_ready_polls_until_ready_on_the_fake_clock(clock: _Clock) -> None:
    plug, fake = _plug(ready_after=2)
    plug.apply_capture(CAPTURE)
    plug.single()
    fake.log.clear()
    plug.wait_ready(timeout_s=5.0, poll_s=0.25)
    assert fake.log == [("ps2000aIsReady", (1,))] * 3  # PG §3.26: 0, 0, then non-zero
    assert clock.sleeps == [0.25, 0.25]


def test_wait_ready_returns_at_once_when_ready() -> None:
    plug, fake = _plug(ready_after=0)
    plug.apply_capture(CAPTURE)
    plug.single()
    fake.log.clear()
    plug.wait_ready()
    assert fake.log == [("ps2000aIsReady", (1,))]


def test_wait_ready_timeout_stops_the_capture(clock: _Clock) -> None:
    plug, fake = _plug(ready_after=10**9)
    plug.apply_capture(CAPTURE)
    plug.single()
    fake.log.clear()
    with pytest.raises(TimeoutError, match="no trigger within 2 s"):
        plug.wait_ready(timeout_s=2.0, poll_s=0.5)
    assert fake.log == [("ps2000aIsReady", (1,))] * 5 + [("ps2000aStop", (1,))]  # PG §3.65
    assert clock.sleeps == [0.5] * 4
    assert not fake.units[1].armed
    with pytest.raises(RuntimeError, match="single"):
        plug.read_waveform(1)


def test_wait_ready_timeout_survives_a_failing_stop() -> None:
    plug, fake = _plug(ready_after=10**9)
    plug.apply_capture(CAPTURE)
    plug.single()
    fake.reject["ps2000aStop"] = "PICO_BUSY"
    with pytest.raises(TimeoutError):
        plug.wait_ready(timeout_s=0.1, poll_s=0.1)


def test_wait_ready_error_raises_pico_error() -> None:
    plug, fake = _plug()
    plug.apply_capture(CAPTURE)
    plug.single()
    fake.reject["ps2000aIsReady"] = "PICO_NOT_RESPONDING"
    with pytest.raises(PicoError) as excinfo:
        plug.wait_ready()
    assert excinfo.value.function == "ps2000aIsReady"
    assert excinfo.value.name == "PICO_NOT_RESPONDING"


def test_wait_ready_before_single_raises() -> None:
    plug, _ = _plug()
    plug.apply_capture(CAPTURE)
    with pytest.raises(RuntimeError, match="single"):
        plug.wait_ready()


def test_read_waveform_makes_one_get_values_for_all_channels() -> None:
    plug, fake = _plug()
    _acquire(plug)
    fake.log.clear()
    w1 = plug.read_waveform(1)
    w2 = plug.read_waveform(2)
    w1_again = plug.read_waveform(1)
    assert fake.log == [("ps2000aGetValues", (1, 0, 2000, 1, NONE, 0))]  # PG §3.18
    assert len(w1.raw) == len(w2.raw) == 2000
    assert np.array_equal(w1.raw, w1_again.raw)
    assert w1.raw is not w1_again.raw  # every call returns its own copy
    assert w1.raw.dtype == np.int16


def test_read_waveform_fetches_again_after_a_new_single() -> None:
    plug, fake = _plug()
    _acquire(plug)
    plug.read_waveform(1)
    plug.single()
    plug.wait_ready()
    fake.log.clear()
    plug.read_waveform(1)
    assert _names(fake) == ["ps2000aGetValues"]


def test_read_waveform_before_single_raises() -> None:
    plug, fake = _plug()
    with pytest.raises(RuntimeError, match="apply_capture"):
        plug.read_waveform(1)
    plug.apply_capture(CAPTURE)
    with pytest.raises(RuntimeError, match="single"):
        plug.read_waveform(1)
    assert "ps2000aGetValues" not in _names(fake)


def test_read_waveform_before_ready_raises() -> None:
    plug, fake = _plug()
    plug.apply_capture(CAPTURE)
    plug.single()
    with pytest.raises(RuntimeError, match="wait_ready"):
        plug.read_waveform(1)
    assert "ps2000aGetValues" not in _names(fake)


def test_read_waveform_of_a_disabled_channel_raises_value_error() -> None:
    plug, fake = _plug()
    _acquire(plug)
    fake.log.clear()
    for ch in (3, 4, 5):
        with pytest.raises(ValueError, match="not enabled"):
            plug.read_waveform(ch)
    assert fake.log == []


def test_get_values_error_raises_and_a_retry_fetches_again() -> None:
    plug, fake = _plug()
    _acquire(plug)
    fake.reject["ps2000aGetValues"] = "PICO_NO_SAMPLES_AVAILABLE"
    with pytest.raises(PicoError) as excinfo:
        plug.read_waveform(1)
    assert excinfo.value.function == "ps2000aGetValues"
    assert excinfo.value.name == "PICO_NO_SAMPLES_AVAILABLE"
    fake.reject.clear()
    assert len(plug.read_waveform(1).raw) == 2000


def test_stop_log_sequence_and_data_stays_readable() -> None:
    plug, fake = _plug()
    _acquire(plug)
    plug.read_waveform(1)
    fake.log.clear()
    plug.stop()
    assert fake.log == [("ps2000aStop", (1,))]
    assert len(plug.read_waveform(2).raw) == 2000  # fetched data is still there, no new call
    assert fake.log == [("ps2000aStop", (1,))]


def test_stop_error_raises_pico_error() -> None:
    plug, fake = _plug()
    fake.reject["ps2000aStop"] = "PICO_DRIVER_FUNCTION"
    with pytest.raises(PicoError) as excinfo:
        plug.stop()
    assert excinfo.value.function == "ps2000aStop"
    assert excinfo.value.name == "PICO_DRIVER_FUNCTION"


def test_ping_and_flash_led_log_sequences_and_errors() -> None:
    plug, fake = _plug()
    plug.ping()
    plug.flash_led()
    plug.flash_led(3)
    assert fake.log == [
        ("ps2000aPingUnit", (1,)),  # PG §3.35
        ("ps2000aFlashLed", (1, 5)),  # PG §3.5
        ("ps2000aFlashLed", (1, 3)),
    ]
    fake.reject["ps2000aPingUnit"] = "PICO_NOT_RESPONDING"
    fake.reject["ps2000aFlashLed"] = "PICO_BUSY"
    with pytest.raises(PicoError) as ping_error:
        plug.ping()
    assert ping_error.value.name == "PICO_NOT_RESPONDING"
    with pytest.raises(PicoError) as led_error:
        plug.flash_led()
    assert led_error.value.function == "ps2000aFlashLed"


# -- conversions ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("interval", "pre", "post"),
    [(1 * us, 100, 4900), (10 * us, 100, 3900)],  # 5 and 40 periods of the 1 kHz clock
)
@pytest.mark.parametrize("range_v", [2 * V, 5 * V])
def test_clock_measures_as_the_fake_generates_it(
    interval: float, pre: int, post: int, range_v: float
) -> None:
    plug, _ = _plug(clock_hz=1000.0, clock_v=1.0)
    _acquire(plug, _single_channel(interval, range_v, pre, post))
    w = plug.read_waveform(1)
    assert measure.vpp(w) == pytest.approx(1.0, rel=1e-3)
    assert measure.vmin(w) == pytest.approx(0.0, abs=1e-3)
    assert measure.vmax(w) == pytest.approx(1.0, rel=1e-3)
    assert measure.frequency_hz(w) == pytest.approx(1000.0, rel=1e-3)
    assert w.t[pre] == 0.0  # the trigger point
    assert w.t[0] == pytest.approx(-pre * interval, rel=1e-6)
    assert w.t[-1] == pytest.approx(post * interval - interval, rel=1e-6)
    assert w.meta.sample_interval_s == pytest.approx(interval, rel=1e-6)
    assert len(w.t) == len(w.v) == len(w.raw) == pre + post
    assert w.raw[pre - 1] == 0 and w.raw[pre] > 0  # RISING trigger: edge at index pre


def test_other_clock_values_convert_with_the_chosen_range() -> None:
    plug, _ = _plug(clock_hz=2500.0, clock_v=0.3)
    _acquire(plug, _single_channel(2 * us, 0.5 * V, 50, 1950))
    w = plug.read_waveform(1)
    assert measure.vpp(w) == pytest.approx(0.3, rel=1e-3)
    assert measure.frequency_hz(w) == pytest.approx(2500.0, rel=1e-3)
    assert w.meta.range_v == 0.5
    assert int(w.raw.max()) == round(0.3 / 0.5 * 32512)  # PG §2.3


def test_waveform_meta_describes_the_capture() -> None:
    plug, _ = _plug()
    _acquire(plug)
    w = plug.read_waveform(2)
    assert w.meta == WaveformMeta(
        channel=2,
        range_v=2.0,
        coupling="DC",
        max_adc=32512,
        sample_interval_s=w.meta.sample_interval_s,
        pre_samples=100,
        timebase=127,
        overflow=False,
        serial="FAKE0/001",
        variant="2207BMSO",
    )
    assert isinstance(w, Waveform)
    assert w.meta.sample_interval_s == pytest.approx(1e-6, rel=1e-6)


def test_waveform_from_raw_round_trip() -> None:
    plug, _ = _plug()
    _acquire(plug)
    w = plug.read_waveform(1)
    again = waveform_from_raw(w.raw, w.meta)
    assert np.array_equal(again.t, w.t)
    assert np.array_equal(again.v, w.v)
    assert np.array_equal(again.raw, w.raw)
    assert again.meta == w.meta


def test_waveform_from_raw_conversion_by_hand() -> None:
    meta = WaveformMeta(
        channel=1,
        range_v=1.0,
        coupling="DC",
        max_adc=32512,
        sample_interval_s=1e-3,
        pre_samples=1,
        timebase=0,
        overflow=False,
        serial="S",
        variant="V",
    )
    raw = np.array([-32512, 0, 16256, 32512], dtype=np.int16)
    w = waveform_from_raw(raw, meta)
    assert w.raw is raw
    assert w.v.tolist() == [-1.0, 0.0, 0.5, 1.0]  # PG §2.3: volts = count * range / max
    assert w.t.tolist() == [-1e-3, 0.0, 1e-3, 2e-3]
    assert w.t.dtype == np.float64 and w.v.dtype == np.float64


@pytest.mark.parametrize("small_channel", [2, 1])
def test_overflow_bit_is_reported_per_channel(small_channel: int) -> None:
    plug, _ = _plug(clock_v=1.0)
    channels = tuple(
        Channel(ch=ch, range=0.5 * V if ch == small_channel else 2 * V) for ch in (1, 2)
    )  # a 1 V clock overdrives the +-0.5 V range
    capture = Capture(channels=channels, sample_interval=1 * us, pre_samples=100, post_samples=1900)
    _acquire(plug, capture)
    clipped = plug.read_waveform(small_channel)
    fine = plug.read_waveform(3 - small_channel)
    assert clipped.meta.overflow is True  # PG §3.18: bit 0 = channel A
    assert fine.meta.overflow is False
    assert int(clipped.raw.max()) == 32512
    with pytest.raises(ClippedError):
        measure.vpp(clipped)
    assert measure.vpp(clipped, allow_clipped=True) == pytest.approx(0.5, rel=1e-3)
    assert measure.vpp(fine) == pytest.approx(1.0, rel=1e-3)


def test_overflow_is_read_from_the_driver_bit_field() -> None:
    class _BitsB(FakePs2000a):
        def ps2000aGetValues(self, *args: Any) -> tuple[int, int, int]:
            status, n, _ = super().ps2000aGetValues(*args)
            return (status, n, 0b0010)  # only channel B overflowed

    fake = _BitsB()
    plug = PicoScope2000Plug(api=fake)
    _acquire(plug)
    assert plug.read_waveform(1).meta.overflow is False
    assert plug.read_waveform(2).meta.overflow is True


def test_fewer_samples_than_requested_are_returned_as_is() -> None:
    class _Short(FakePs2000a):
        def ps2000aGetValues(self, *args: Any) -> tuple[int, int, int]:
            status, n, overflow = super().ps2000aGetValues(*args)
            return (status, n - 500, overflow)

    plug = PicoScope2000Plug(api=_Short())
    _acquire(plug)
    w = plug.read_waveform(1)
    assert len(w.raw) == len(w.t) == len(w.v) == 1500


# -- teardown and the closed plug -------------------------------------------------------------


def test_teardown_stops_and_closes_once() -> None:
    plug, fake = _plug()
    plug.tearDown()
    assert fake.log == [("ps2000aStop", (1,)), ("ps2000aCloseUnit", (1,))]  # PG §3.65, §3.2
    assert fake.closed_handles == [1]
    assert fake.units == {}
    plug.tearDown()
    assert len(fake.log) == 2  # idempotent: nothing is sent twice
    assert fake.closed_handles == [1]


def test_teardown_swallows_rejected_calls_and_logs_warnings(
    caplog: pytest.LogCaptureFixture,
) -> None:
    plug, fake = _plug()
    fake.reject["ps2000aStop"] = "PICO_BUSY"
    fake.reject["ps2000aCloseUnit"] = "PICO_NOT_RESPONDING"
    with caplog.at_level(logging.INFO):
        plug.tearDown()
    assert fake.log == [("ps2000aStop", (1,)), ("ps2000aCloseUnit", (1,))]  # both are attempted
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == [
        "ps2000aStop returned PICO_BUSY",
        "ps2000aCloseUnit returned PICO_NOT_RESPONDING",
    ]
    plug.tearDown()
    assert len(fake.log) == 2


def test_teardown_swallows_exceptions(caplog: pytest.LogCaptureFixture) -> None:
    plug, fake = _plug()

    def boom(handle: int) -> tuple[int]:
        raise OSError("usb gone")

    fake.ps2000aStop = boom  # type: ignore[method-assign]
    fake.ps2000aCloseUnit = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING):
        plug.tearDown()  # must not raise
    assert [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING] == [
        "ps2000aStop failed",
        "ps2000aCloseUnit failed",
    ]


def test_teardown_stops_a_running_capture() -> None:
    plug, fake = _plug(ready_after=10**9)
    plug.apply_capture(CAPTURE)
    plug.single()
    assert fake.units[1].armed
    plug.tearDown()
    assert fake.closed_handles == [1]


def test_the_unit_can_be_opened_again_after_teardown() -> None:
    fake = FakePs2000a()
    PicoScope2000Plug(api=fake).tearDown()
    assert PicoScope2000Plug(api=fake).serial == "FAKE0/001"  # PG §3.4: unopened again


def test_methods_after_teardown_raise_plug_closed() -> None:
    plug, fake = _plug()
    plug.apply_capture(CAPTURE)
    plug.tearDown()
    fake.log.clear()
    calls: list[Any] = [
        lambda: plug.apply_capture(CAPTURE),
        plug.single,
        plug.wait_ready,
        lambda: plug.read_waveform(1),
        plug.stop,
        plug.ping,
        plug.flash_led,
    ]
    for call in calls:
        with pytest.raises(RuntimeError, match="^plug closed$"):
            call()
    assert fake.log == []
    assert plug.serial == "FAKE0/001"  # identity stays readable


# -- OpenHTF ----------------------------------------------------------------------------------


def _openhtf_phase(fake: FakePs2000a, range_v: float = 2 * V) -> Any:
    class FakePlug(PicoScope2000Plug):
        def __init__(self) -> None:
            super().__init__(api=fake)

    capture = Capture(
        channels=(Channel(ch=1, range=range_v), Channel(ch=2, range=range_v)),
        sample_interval=1 * us,
        pre_samples=100,
        post_samples=4900,
        trigger=Edge(source=1, level=0.5 * V, auto_ms=1000),
    )

    @htf.plug(scope=FakePlug)
    @htf.measures(
        htf.Measurement("vpp_ch1").in_range(0.9, 1.1),
        htf.Measurement("freq_ch1").in_range(990, 1010),
        htf.Measurement("num_points").equals(5000),
    )
    def phase(test: Any, scope: FakePlug) -> None:
        scope.apply_capture(capture)
        scope.single()
        scope.wait_ready(poll_s=0.0)
        w = scope.read_waveform(1)
        test.measurements.vpp_ch1 = measure.vpp(w)
        test.measurements.freq_ch1 = measure.frequency_hz(w)
        test.measurements.num_points = len(w.v)
        scope.stop()

    return phase


def test_openhtf_integration_passes_and_tears_down() -> None:
    fake = FakePs2000a()
    outcome = htf.Test(_openhtf_phase(fake)).execute(test_start=lambda: "dut-1")
    assert outcome is True  # PASS
    assert _names(fake)[:2] == ["ps2000aEnumerateUnits", "ps2000aOpenUnit"]
    assert _names(fake)[-3:] == [
        "ps2000aStop",
        "ps2000aStop",
        "ps2000aCloseUnit",
    ]  # phase, tearDown
    assert fake.closed_handles == [1]
    assert fake.units == {}


def test_openhtf_failing_measurement_still_tears_down() -> None:
    fake = FakePs2000a(clock_v=1.5)  # vpp 1.5 V, outside 0.9..1.1
    assert htf.Test(_openhtf_phase(fake)).execute(test_start=lambda: "dut-1") is False
    assert fake.closed_handles == [1]


def test_openhtf_pico_error_fails_the_phase_and_still_tears_down() -> None:
    fake = FakePs2000a()
    fake.reject["ps2000aRunBlock"] = "PICO_BUSY"
    assert htf.Test(_openhtf_phase(fake)).execute(test_start=lambda: "dut-1") is False
    assert fake.closed_handles == [1]
