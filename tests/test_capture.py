import dataclasses
import re
from pathlib import Path
from typing import Any

import pytest

from picoscope_2000_openhtf.capture import (
    CHANNEL_NAMES,
    COUPLINGS,
    DIRECTIONS,
    RANGES,
    Capture,
    Channel,
    Edge,
)
from picoscope_2000_openhtf.units import V, mV, us

MANUAL = Path(__file__).parent.parent / "docs" / "picoscope-2000-series-a-api-programmers-guide.txt"


def _capture(**kw: Any) -> Capture:
    args: dict[str, Any] = {
        "channels": (Channel(ch=1, range=2 * V), Channel(ch=2, range=1 * V)),
        "sample_interval": 1 * us,
        "pre_samples": 100,
        "post_samples": 1900,
    }
    args.update(kw)
    return Capture(**args)


# --- tables ---------------------------------------------------------------------------------


def test_ranges_are_the_manuals_ten() -> None:
    assert dict(RANGES) == {
        0.02: "PS2000A_20MV",
        0.05: "PS2000A_50MV",
        0.1: "PS2000A_100MV",
        0.2: "PS2000A_200MV",
        0.5: "PS2000A_500MV",
        1.0: "PS2000A_1V",
        2.0: "PS2000A_2V",
        5.0: "PS2000A_5V",
        10.0: "PS2000A_10V",
        20.0: "PS2000A_20V",
    }


def test_other_tables() -> None:
    assert dict(CHANNEL_NAMES) == {
        1: "PS2000A_CHANNEL_A",
        2: "PS2000A_CHANNEL_B",
        3: "PS2000A_CHANNEL_C",
        4: "PS2000A_CHANNEL_D",
    }
    assert dict(COUPLINGS) == {"AC": "PS2000A_AC", "DC": "PS2000A_DC"}
    assert dict(DIRECTIONS) == {
        "ABOVE": "PS2000A_ABOVE",
        "BELOW": "PS2000A_BELOW",
        "RISING": "PS2000A_RISING",
        "FALLING": "PS2000A_FALLING",
        "RISING_OR_FALLING": "PS2000A_RISING_OR_FALLING",
    }


def test_every_enum_name_appears_verbatim_in_the_manual() -> None:
    text = MANUAL.read_text(encoding="utf-8")
    names = [*RANGES.values(), *CHANNEL_NAMES.values(), *COUPLINGS.values(), *DIRECTIONS.values()]
    missing = [n for n in names if not re.search(rf"\b{n}\b", text)]
    assert missing == []


# --- Channel --------------------------------------------------------------------------------


def test_channel_defaults_and_frozen() -> None:
    c = Channel(ch=1, range=2 * V)
    assert (c.ch, c.range, c.coupling) == (1, 2.0, "DC")
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.ch = 2  # type: ignore[misc]


def test_channel_kw_only() -> None:
    with pytest.raises(TypeError):
        Channel(1, 2.0)  # type: ignore[call-arg]


@pytest.mark.parametrize("ch", [0, 5, -1, 1.5, "1", True, None])
def test_channel_rejects_bad_ch(ch: Any) -> None:
    with pytest.raises(ValueError, match="ch must be"):
        Channel(ch=ch, range=1.0)


@pytest.mark.parametrize("rng", [0.0, 0.3, 50.0, -1.0, "1", None, True, float("nan")])
def test_channel_rejects_bad_range(rng: Any) -> None:
    with pytest.raises(ValueError, match="range must be one of"):
        Channel(ch=1, range=rng)


@pytest.mark.parametrize("key", list(RANGES))
def test_channel_accepts_every_range_and_normalises(key: float) -> None:
    c = Channel(ch=2, range=key * (1 + 1e-12))
    assert c.range == key


def test_channel_range_from_units_and_int() -> None:
    assert Channel(ch=1, range=200 * mV).range == 0.2
    assert Channel(ch=1, range=5).range == 5.0
    assert Channel(ch=1, range=10 * V).range == 10.0


def test_channel_rejects_bad_coupling() -> None:
    with pytest.raises(ValueError, match="coupling must be"):
        Channel(ch=1, range=1.0, coupling="GND")  # type: ignore[arg-type]
    assert Channel(ch=1, range=1.0, coupling="AC").coupling == "AC"


def test_channel_reports_all_problems() -> None:
    with pytest.raises(ValueError) as exc:
        Channel(ch=9, range=3.0, coupling="X")  # type: ignore[arg-type]
    msg = str(exc.value)
    assert msg.count("; ") == 2
    assert "ch must be" in msg
    assert "range must be" in msg
    assert "coupling must be" in msg


# --- Edge -----------------------------------------------------------------------------------


def test_edge_defaults() -> None:
    e = Edge(source=1, level=0.5)
    assert (e.direction, e.auto_ms, e.delay_samples) == ("RISING", 0, 0)


@pytest.mark.parametrize("d", list(DIRECTIONS))
def test_edge_accepts_every_direction(d: Any) -> None:
    assert Edge(source=1, level=0.0, direction=d).direction == d


def test_edge_rejects_bad_direction() -> None:
    with pytest.raises(ValueError, match="direction must be"):
        Edge(source=1, level=0.0, direction="UP")  # type: ignore[arg-type]


@pytest.mark.parametrize("src", [0, 5, 2.0, "A", True])
def test_edge_rejects_bad_source(src: Any) -> None:
    with pytest.raises(ValueError, match="source must be"):
        Edge(source=src, level=0.0)


@pytest.mark.parametrize("level", [float("nan"), float("inf"), "0.5", None])
def test_edge_rejects_bad_level(level: Any) -> None:
    with pytest.raises(ValueError, match="level must be"):
        Edge(source=1, level=level)


@pytest.mark.parametrize("auto", [-1, 32768, 1.5, "10", True])
def test_edge_rejects_bad_auto_ms(auto: Any) -> None:
    with pytest.raises(ValueError, match="auto_ms must be"):
        Edge(source=1, level=0.0, auto_ms=auto)


def test_edge_auto_ms_bounds_inclusive() -> None:
    assert Edge(source=1, level=0.0, auto_ms=0).auto_ms == 0
    assert Edge(source=1, level=0.0, auto_ms=32767).auto_ms == 32767


@pytest.mark.parametrize("delay", [-1, 0.5, "1", True])
def test_edge_rejects_bad_delay(delay: Any) -> None:
    with pytest.raises(ValueError, match="delay_samples must be"):
        Edge(source=1, level=0.0, delay_samples=delay)


def test_edge_reports_all_problems() -> None:
    with pytest.raises(ValueError) as exc:
        Edge(source=7, level=float("nan"), direction="X", auto_ms=-5, delay_samples=-2)  # type: ignore[arg-type]
    msg = str(exc.value)
    assert msg.count("; ") == 4
    for part in ("source", "level", "direction", "auto_ms", "delay_samples"):
        assert part in msg


# --- Capture --------------------------------------------------------------------------------


def test_capture_valid() -> None:
    c = _capture(trigger=Edge(source=1, level=0.5 * V, auto_ms=1000))
    assert c.total_samples == 2000
    assert c.enabled() == (1, 2)
    assert c.channel(2).range == 1.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.pre_samples = 5  # type: ignore[misc]


def test_capture_kw_only() -> None:
    with pytest.raises(TypeError):
        Capture((Channel(ch=1, range=1.0),), 1e-6, 1, 1)  # type: ignore[call-arg]


def test_capture_accepts_one_to_four_channels() -> None:
    for n in range(1, 5):
        chans = tuple(Channel(ch=i, range=1.0) for i in range(1, n + 1))
        assert _capture(channels=chans).enabled() == tuple(range(1, n + 1))


def test_capture_enabled_is_sorted() -> None:
    chans = (Channel(ch=3, range=1.0), Channel(ch=1, range=1.0))
    assert _capture(channels=chans).enabled() == (1, 3)


def test_capture_list_of_channels_becomes_tuple() -> None:
    c = _capture(channels=[Channel(ch=1, range=1.0)])
    assert isinstance(c.channels, tuple)


def test_capture_rejects_no_channels() -> None:
    with pytest.raises(ValueError, match="1..4 entries, got 0"):
        _capture(channels=())


def test_capture_rejects_too_many_channels() -> None:
    chans = tuple(Channel(ch=1 + i % 4, range=1.0) for i in range(5))
    with pytest.raises(ValueError, match="1..4 entries, got 5"):
        _capture(channels=chans)


def test_capture_rejects_duplicate_channels() -> None:
    chans = (Channel(ch=1, range=1.0), Channel(ch=1, range=2.0))
    with pytest.raises(ValueError, match=r"distinct, repeated: \[1\]"):
        _capture(channels=chans)


def test_capture_rejects_non_channel_entries() -> None:
    with pytest.raises(ValueError, match="tuple of Channel"):
        _capture(channels=(1, 2))


@pytest.mark.parametrize("si", [0.0, -1e-6, float("nan"), float("inf"), "1e-6", None])
def test_capture_rejects_bad_sample_interval(si: Any) -> None:
    with pytest.raises(ValueError, match="sample_interval must be"):
        _capture(sample_interval=si)


@pytest.mark.parametrize("field", ["pre_samples", "post_samples"])
@pytest.mark.parametrize("bad", [-1, 1.5, "3", None])
def test_capture_rejects_bad_counts(field: str, bad: Any) -> None:
    with pytest.raises(ValueError, match=f"{field} must be"):
        _capture(**{field: bad})


def test_capture_rejects_zero_total() -> None:
    with pytest.raises(ValueError, match="must be > 0"):
        _capture(pre_samples=0, post_samples=0)


def test_capture_allows_zero_pre_or_post() -> None:
    assert _capture(pre_samples=0, post_samples=10).total_samples == 10
    assert _capture(pre_samples=10, post_samples=0).total_samples == 10


def test_capture_rejects_trigger_on_disabled_channel() -> None:
    with pytest.raises(ValueError, match="trigger source 3 is not one of the channels"):
        _capture(trigger=Edge(source=3, level=0.0))


def test_capture_trigger_level_vs_range() -> None:
    ok = _capture(trigger=Edge(source=2, level=1.0 * V))  # channel 2 range is 1 V
    assert ok.trigger is not None
    assert _capture(trigger=Edge(source=2, level=-1.0 * V)).trigger is not None
    with pytest.raises(ValueError, match="exceeds the range 1 V of channel 2"):
        _capture(trigger=Edge(source=2, level=1.01))
    with pytest.raises(ValueError, match="exceeds the range"):
        _capture(trigger=Edge(source=2, level=-1.01))


def test_capture_rejects_non_edge_trigger() -> None:
    with pytest.raises(ValueError, match="trigger must be an Edge or None"):
        _capture(trigger="rising")


def test_capture_reports_all_problems_at_once() -> None:
    with pytest.raises(ValueError) as exc:
        _capture(
            channels=(Channel(ch=1, range=1.0), Channel(ch=1, range=1.0)),
            sample_interval=0.0,
            pre_samples=-1,
            post_samples=-2,
            trigger=Edge(source=1, level=5.0),
        )
    msg = str(exc.value)
    parts = msg.removeprefix("invalid Capture: ").split("; ")
    assert len(parts) == 5
    assert "distinct" in msg
    assert "sample_interval" in msg
    assert "pre_samples" in msg
    assert "post_samples" in msg
    assert "exceeds the range" in msg


def test_capture_all_problems_with_missing_trigger_source_and_zero_total() -> None:
    with pytest.raises(ValueError) as exc:
        _capture(
            channels=(),
            sample_interval=-1.0,
            pre_samples=0,
            post_samples=0,
            trigger=Edge(source=1, level=0.0),
        )
    msg = str(exc.value)
    assert "1..4 entries" in msg
    assert "sample_interval" in msg
    assert "must be > 0" in msg


# --- lookup and conversion ------------------------------------------------------------------


def test_channel_lookup() -> None:
    c = _capture()
    assert c.channel(1).range == 2.0
    with pytest.raises(ValueError, match="channel 3 is not enabled"):
        c.channel(3)


def test_trigger_threshold_adc_examples() -> None:
    def cap(level: float) -> Capture:
        return _capture(channels=(Channel(ch=1, range=2 * V),), trigger=Edge(source=1, level=level))

    assert cap(2.0).trigger_threshold_adc(32512) == 32512
    assert cap(0.0).trigger_threshold_adc(32512) == 0
    assert cap(-1.0).trigger_threshold_adc(32512) == -16256
    assert cap(-2.0).trigger_threshold_adc(32512) == -32512
    assert cap(0.5).trigger_threshold_adc(32512) == 8128


def test_trigger_threshold_uses_source_channel_range() -> None:
    c = _capture(trigger=Edge(source=2, level=0.5 * V))  # channel 2 is 1 V range
    assert c.trigger_threshold_adc(32512) == 16256


def test_trigger_threshold_rounds() -> None:
    c = _capture(channels=(Channel(ch=1, range=5 * V),), trigger=Edge(source=1, level=0.1234 * V))
    assert c.trigger_threshold_adc(32512) == round(0.1234 / 5 * 32512)


def test_trigger_threshold_without_trigger() -> None:
    with pytest.raises(ValueError, match="no trigger"):
        _capture().trigger_threshold_adc(32512)
