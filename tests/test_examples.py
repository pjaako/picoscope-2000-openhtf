"""Tests for ``example_test.py`` and ``tools/probe.py``.

No hardware, no network: the example runs with ``--fake`` and the probe runs against a
``FakePs2000a`` injected through its ``api`` hook.
"""

import importlib
import io
import sys
from pathlib import Path
from typing import Any

import pytest

from picoscope_2000_openhtf import driver
from picoscope_2000_openhtf.fake_resource import FakePs2000a
from tools import probe

ITEM_TITLES = [f"## {n}. " for n in range(1, 9)]


@pytest.fixture(autouse=True)
def _no_serial_in_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PICOSCOPE_SERIAL", raising=False)


def _refuse_picosdk_api(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a PicosdkApi was constructed")

    monkeypatch.setattr(driver.PicosdkApi, "__init__", refuse)


def test_example_runs_with_fake(capsys: pytest.CaptureFixture[str]) -> None:
    import example_test

    assert example_test.main(["--fake"]) == 0
    out = capsys.readouterr().out
    assert "example: PASS" in out
    assert "example: FAIL" not in out


def test_example_fake_needs_no_picosdk_api(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import example_test

    _refuse_picosdk_api(monkeypatch)
    assert example_test.main(["--fake"]) == 0
    assert "example: PASS" in capsys.readouterr().out


def test_example_capture_is_the_spec_capture() -> None:
    import example_test

    capture = example_test.CAPTURE
    assert [(c.ch, c.range) for c in capture.channels] == [(1, 2.0), (2, 2.0)]
    assert capture.sample_interval == pytest.approx(1e-6)
    assert (capture.pre_samples, capture.post_samples) == (100, 1900)
    assert capture.trigger is not None
    assert (capture.trigger.source, capture.trigger.level, capture.trigger.auto_ms) == (
        1,
        0.5,
        1000,
    )


@pytest.mark.parametrize("module", ["example_test", "tools.probe"])
def test_import_opens_no_unit(module: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _refuse_picosdk_api(monkeypatch)
    monkeypatch.delitem(sys.modules, module, raising=False)  # fresh import; restored after the test
    importlib.import_module(module)
    assert "picosdk.ps2000a" not in sys.modules


# -- probe --------------------------------------------------------------------------------


def _run_probe(tmp_path: Path, fake: FakePs2000a, *flags: str) -> tuple[int, str, Path, str]:
    out = tmp_path / "nested" / "dumps"  # the probe creates the directory
    stream = io.StringIO()
    code = probe.main(["--out", str(out), *flags], api=fake, stream=stream)
    reports = list(out.glob("probe-*.md"))
    assert len(reports) == 1
    return code, reports[0].read_text(encoding="utf-8"), reports[0], stream.getvalue()


def test_probe_writes_report_with_every_item(tmp_path: Path) -> None:
    fake = FakePs2000a()
    code, text, path, streamed = _run_probe(tmp_path, fake)
    assert code == 0
    assert path.name.startswith("probe-") and path.suffix == ".md"
    assert streamed == text  # the stream mirrors the file
    for title in ITEM_TITLES:
        assert title in text
    assert "PICO_OK" in text
    assert "WARNING: no --serial" in text
    # exact calls and statuses
    assert "-> ps2000aEnumerateUnits()\n<- PICO_OK, 1, 'FAKE0/001'" in text
    assert "-> ps2000aGetTimebase2(1, 10000, 1000, 0, 0)" in text
    assert (
        "-> ps2000aSetChannel(1, 'PS2000A_CHANNEL_A', 1, 'PS2000A_DC', 'PS2000A_20MV', 0.0)" in text
    )
    assert "ps2000aSetDataBuffer(1, 'PS2000A_CHANNEL_A', <int16[2000]>" in text
    assert (
        "ps2000aSetSimpleTrigger(1, 1, 'PS2000A_CHANNEL_A', 8128, 'PS2000A_RISING', 0, 2000)"
        in text
    )
    assert "ps2000aRunBlock(1, 100, 1900, " in text
    assert "ps2000aGetValues(1, 0, 2000, 1, 'PS2000A_RATIO_MODE_NONE', 0)" in text
    assert "overflow bit 0" in text
    assert "accepted: PS2000A_20MV (0.02 V)" in text
    assert "rejected: none" in text
    assert "## Teardown" in text
    names = [name for name, _ in fake.log]
    assert "ps2000aCloseUnit" in names
    assert names.index("ps2000aCloseUnit") > names.index("ps2000aGetValues")
    assert fake.units == {}  # the unit was closed


def test_probe_serial_flag_and_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakePs2000a(serials=("FAKE0/001", "FAKE0/002"))
    code, text, _, _ = _run_probe(tmp_path / "flag", fake, "--serial", "FAKE0/002")
    assert code == 0
    assert "WARNING" not in text
    assert ("ps2000aOpenUnit", ("FAKE0/002",)) in fake.log

    monkeypatch.setenv("PICOSCOPE_SERIAL", "FAKE0/001")
    fake = FakePs2000a(serials=("FAKE0/001", "FAKE0/002"))
    code, text, _, _ = _run_probe(tmp_path / "env", fake)
    assert code == 0
    assert ("ps2000aOpenUnit", ("FAKE0/001",)) in fake.log


def test_probe_failing_item_does_not_stop_the_run(tmp_path: Path) -> None:
    fake = FakePs2000a()
    fake.reject["ps2000aGetTimebase2"] = "PICO_INVALID_TIMEBASE"
    code, text, _, _ = _run_probe(tmp_path, fake)
    assert code == 0
    assert "PICO_INVALID_TIMEBASE" in text
    for title in ITEM_TITLES:
        assert title in text
    assert "item failed: CaptureError" in text  # items 6 and 7: no timebase found
    assert "-> ps2000aCloseUnit(1)" in text
    assert fake.units == {}


def test_probe_records_a_raising_driver_and_continues(tmp_path: Path) -> None:
    class Flaky(FakePs2000a):
        def ps2000aMaximumValue(self, handle: int) -> tuple[int, int]:
            raise OSError("usb gone")

    fake = Flaky()
    code, text, _, _ = _run_probe(tmp_path, fake)
    # the plug constructor needs MaximumValue: opening fails, the run still reports every item
    assert code == 1
    assert "!! OSError: usb gone" in text
    for title in ITEM_TITLES:
        assert title in text
    assert fake.units == {}  # the plug closed the handle it had opened


def test_probe_without_a_unit_reports_and_returns_nonzero(tmp_path: Path) -> None:
    fake = FakePs2000a(serials=())
    code, text, _, _ = _run_probe(tmp_path, fake)
    assert code != 0
    for title in ITEM_TITLES:
        assert title in text
    assert "PICO_NOT_FOUND" in text
    assert "item failed: PicoError" in text
    assert "item failed: RuntimeError: no unit is open" in text
    assert "RESULT: no unit was opened" in text


def test_probe_serial_not_found_returns_nonzero(tmp_path: Path) -> None:
    code, text, _, _ = _run_probe(tmp_path, FakePs2000a(), "--serial", "NOPE/000")
    assert code != 0
    assert "PICO_NOT_FOUND" in text


def test_probe_without_native_driver_does_not_raise(tmp_path: Path) -> None:
    # api=None builds PicosdkApi(), which imports picosdk.ps2000a on its first call; without the
    # native library (as in CI) that raises inside item 1 and is recorded.
    out = tmp_path / "dumps"
    stream = io.StringIO()
    try:
        import picosdk.ps2000a  # noqa: F401
    except Exception:
        code = probe.main(["--out", str(out)], stream=stream)
        assert code != 0
        assert "!! " in stream.getvalue()
