"""Hardware probe for the PicoScope 2000 Series (A API). Owner-run; coder agents never run it.

Usage:
    python tools/probe.py [--serial SER] [--out dumps]

The serial number comes from --serial or the environment variable PICOSCOPE_SERIAL; with neither,
the first unit found is opened and the report says so. Runs the items of SPEC section 9 in order,
records every driver call (function, arguments, status name) and writes
``<out>/probe-<YYYYmmdd-HHMMSS>.md`` incrementally, mirrored on the stream (stdout). Every item
catches its exceptions, records them and lets the next item run. The unit is stopped and closed at
the end. Nothing on a scope input is risky, so there is no --risky gate.

"PG" = PicoScope 2000 Series (A API) Programmer's Guide, ps2000apg.en-12 (docs/api_reference.md).
The answers of this run go to README "Things the manual does not tell you" and to the fake.
"""

import argparse
import os
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO, cast

import numpy as np
import numpy.typing as npt

from picoscope_2000_openhtf import Capture, Channel, Edge, PicoScope2000Plug
from picoscope_2000_openhtf.capture import CHANNEL_NAMES, COUPLINGS, RANGES
from picoscope_2000_openhtf.driver import PicosdkApi, Ps2000aApi, status_name
from picoscope_2000_openhtf.units import V, us

TIMEBASES = (*range(11), 100, 1000, 10000)  # SPEC §9 item 4; PG §2.7 tables, §3.14
TIMEBASE_SAMPLES = 1000  # noSamples passed to ps2000aGetTimebase2 in item 4
CAPTURE_SAMPLES = 2000  # SPEC §9 items 6 and 7
PRE_SAMPLES = 100  # item 7: samples before the trigger point
WAIT_S = 10.0  # item 6, 7: more than the 2 s auto trigger of item 7
_TWO_V = RANGES[2 * V]  # PG §3.39
_DC = COUPLINGS["DC"]  # PG §3.39


def _fmt(value: object) -> str:
    if isinstance(value, np.ndarray):
        return f"<{value.dtype}[{value.size}]>"
    return repr(value)


def _modulo_stats(raw: npt.NDArray[np.int16]) -> str:
    """Statistics of ``raw % 256`` (open question 32: an 8-bit ADC gives multiples of 256)."""
    residues = raw.astype(np.int64) % 256
    values, counts = np.unique(residues, return_counts=True)
    top = int(values[int(np.argmax(counts))])
    multiples = int(np.count_nonzero(residues == 0))
    return (
        f"raw % 256: {multiples} of {raw.size} samples are multiples of 256, "
        f"{values.size} distinct residues, most common residue {top} "
        f"({int(counts.max())} samples), all multiples of 256: "
        f"{'yes' if multiples == raw.size else 'no'}"
    )


class Recorder:
    """Wraps any `Ps2000aApi` and logs every call: -> name(args), <- STATUS, !! error.

    Attribute access returns a logging wrapper for every ``ps2000a*`` name, so each method of the
    Protocol is covered without being repeated here. The status name comes from the first element
    of the returned tuple (PG §4.1); the other outputs follow it. An exception is logged and
    re-raised.
    """

    def __init__(self, api: Ps2000aApi) -> None:
        self._api = api
        self.lines: list[str] = []
        self.muted = False

    def _log(self, line: str) -> None:
        if not self.muted:
            self.lines.append(line)

    def __getattr__(self, name: str) -> Callable[..., Any]:
        if not name.startswith("ps2000a"):
            raise AttributeError(name)
        function = getattr(self._api, name)

        def call(*args: object) -> Any:
            self._log(f"-> {name}({', '.join(_fmt(a) for a in args)})")
            try:
                result = function(*args)
            except Exception as exc:
                self._log(f"!! {type(exc).__name__}: {exc}")
                raise
            rest = "".join(f", {_fmt(x)}" for x in result[1:])
            self._log(f"<- {status_name(result[0])}{rest}")
            return result

        return call

    def take(self) -> list[str]:
        lines, self.lines = self.lines, []
        return lines


class Report:
    """Appends to the report file and echoes to the stream, section by section."""

    def __init__(self, path: Path, stream: TextIO) -> None:
        self.path = path
        self._stream = stream

    def emit(self, text: str) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(text)
        self._stream.write(text)
        self._stream.flush()

    def section(self, title: str, lines: Sequence[str], notes: Sequence[str] = ()) -> None:
        body = "\n".join(lines) if lines else "(no driver call)"
        text = f"## {title}\n\n```\n{body}\n```\n\n"
        if notes:
            text += "\n".join(f"- {note}" for note in notes) + "\n\n"
        self.emit(text)


class Probe:
    """The items. They record through the recorder and return notes; `call` swallows exceptions."""

    def __init__(self, recorder: Recorder, serial: str | None) -> None:
        self.api = cast(Ps2000aApi, recorder)  # the Recorder is a transparent proxy of an api
        self.rec = recorder
        self.serial = serial
        self.plug: PicoScope2000Plug | None = None

    # -- helpers ----------------------------------------------------------------------------

    def call(self, name: str, *args: object) -> tuple[Any, ...] | None:
        """One driver call through the recorder; None when it raised (the recorder logged it)."""
        try:
            result: tuple[Any, ...] = getattr(self.api, name)(*args)
        except Exception:
            return None
        return result

    def open_plug(self) -> PicoScope2000Plug:
        if self.plug is None:
            raise RuntimeError("no unit is open (item 2 failed)")
        return self.plug

    def handle(self) -> int:
        plug = self.open_plug()
        # The plug has no public handle attribute; the raw calls of items 3, 4 and 5 need the one it
        # opened, so this reads the private one (SPEC §9 allows it).
        handle = plug._handle
        if handle is None:
            raise RuntimeError("plug closed")
        return handle

    # -- items ------------------------------------------------------------------------------

    def item_1_enumerate(self) -> list[str]:
        result = self.call("ps2000aEnumerateUnits")  # PG §3.4
        if result is None:
            return ["ps2000aEnumerateUnits raised"]
        status, count, serials = result
        return [f"status {status_name(status)}, count {count}, serials {serials!r}"]

    def item_2_open_and_info(self) -> list[str]:
        # The plug constructor does ps2000aEnumerateUnits, ps2000aOpenUnit (PG §3.32), eleven
        # ps2000aGetUnitInfo calls (PG §3.17) and ps2000aMaximumValue/MinimumValue.
        self.plug = PicoScope2000Plug(self.serial, api=self.api)
        plug = self.plug
        notes = [f"handle {self.handle()}, serial `{plug.serial}`, variant `{plug.variant}`"]
        notes += [f"{name}: `{text}`" for name, text in plug.info.items()]
        return notes

    def item_3_adc_limits(self) -> list[str]:
        handle = self.handle()
        high = self.call("ps2000aMaximumValue", handle)  # PG §3.28
        low = self.call("ps2000aMinimumValue", handle)  # PG §3.30
        return [
            f"MaximumValue {high[1] if high else None}, MinimumValue {low[1] if low else None} "
            "(PG §2.3 says 32512 and -32512)"
        ]

    def item_4_timebases(self) -> list[str]:
        handle = self.handle()
        notes: list[str] = []
        for label, enabled in (("one channel (A)", (1,)), ("two channels (A, B)", (1, 2))):
            for ch, name in CHANNEL_NAMES.items():
                self.call(
                    "ps2000aSetChannel",  # PG §3.39
                    handle,
                    name,
                    int(ch in enabled),
                    _DC,
                    _TWO_V,
                    0.0,
                )
            rows: list[str] = []
            max_samples_seen: list[int] = []
            for n in TIMEBASES:
                result = self.call(
                    "ps2000aGetTimebase2",  # PG §3.14
                    handle,
                    n,
                    TIMEBASE_SAMPLES,
                    0,
                    0,
                )
                if result is None:
                    rows.append(f"n={n}: raised")
                    continue
                status, interval_ns, max_samples = result
                if status_name(status) == "PICO_OK":
                    max_samples_seen.append(max_samples)
                rows.append(
                    f"n={n}: {status_name(status)}, interval {interval_ns:g} ns, "
                    f"maxSamples {max_samples}"
                )
            notes.append(f"{label}, noSamples {TIMEBASE_SAMPLES}:")
            notes += [f"  {row}" for row in rows]
            # Q31 (docs/api_reference.md): compare the per-channel maxSamples above with the
            # total over all channels that ps2000aMemorySegments reports for one segment (PG §3.29).
            # Asking for 1 segment is the state after OpenUnit, so it changes nothing.
            segments = self.call("ps2000aMemorySegments", handle, 1)  # PG §3.29
            if segments is None:
                notes.append("  ps2000aMemorySegments raised")
            else:
                status, n_max_samples = segments
                seen = f"maxSamples {sorted(set(max_samples_seen))}" if max_samples_seen else "none"
                notes.append(
                    f"  ps2000aMemorySegments(1): {status_name(status)}, nMaxSamples "
                    f"{n_max_samples} (total over all channels, PG §3.29) next to {seen} above "
                    "(open question 31: a digital port may take a share of the memory)"
                )
        return notes

    def item_5_ranges(self) -> list[str]:
        handle = self.handle()
        accepted: list[str] = []
        rejected: list[str] = []
        for volts, name in RANGES.items():
            result = self.call(
                "ps2000aSetChannel",  # PG §3.39
                handle,
                CHANNEL_NAMES[1],
                1,
                _DC,
                name,
                0.0,
            )
            ok = result is not None and status_name(result[0]) == "PICO_OK"
            (accepted if ok else rejected).append(f"{name} ({volts:g} V)")
        return [
            f"accepted: {', '.join(accepted) or 'none'}",
            f"rejected: {', '.join(rejected) or 'none'}",
        ]

    def _capture(self, capture: Capture, *, adc_stats: bool = False) -> list[str]:
        plug = self.open_plug()
        notes: list[str] = []
        try:
            plug.apply_capture(capture)
            notes.append(
                f"timebase {plug.timebase}, interval {plug.sample_interval_s:g} s, "
                f"maxSamples {plug.max_samples}"
            )
            plug.single()
            notes.append(f"timeIndisposedMs {plug.time_indisposed_ms}")
            start = time.perf_counter()
            plug.wait_ready(WAIT_S)
            notes.append(f"ready after {(time.perf_counter() - start) * 1000:.0f} ms")
            for ch in capture.enabled():
                w = plug.read_waveform(ch)
                raw: npt.NDArray[np.int16] = w.raw
                notes.append(
                    f"channel {ch}: {len(raw)} samples, raw min {int(raw.min())}, "
                    f"raw max {int(raw.max())}, mean {statistics.fmean(raw.tolist()):.1f}, "
                    f"overflow bit {int(w.meta.overflow)}"
                )
                if adc_stats:
                    notes.append(f"channel {ch}: {_modulo_stats(raw)}")
                if capture.trigger is not None:
                    pre = capture.pre_samples
                    around = raw[max(0, pre - 5) : pre + 6].tolist()
                    notes.append(
                        f"channel {ch}: raw[{max(0, pre - 5)}..{pre + 5}] around index {pre} "
                        f"(threshold {capture.trigger_threshold_adc(plug.max_adc)} counts): "
                        f"{around}"
                    )
        finally:
            self.call(
                "ps2000aStop", self.handle()
            )  # PG §3.65: also ends a capture that never fired
        return notes

    def item_6_capture_no_trigger(self) -> list[str]:
        return self._capture(
            Capture(
                channels=(Channel(ch=1, range=2 * V), Channel(ch=2, range=2 * V)),
                sample_interval=1 * us,
                pre_samples=0,
                post_samples=CAPTURE_SAMPLES,
            ),
            adc_stats=True,  # open question 32: are the codes multiples of 256 (8-bit ADC)?
        )

    def item_7_capture_rising(self) -> list[str]:
        return self._capture(
            Capture(
                channels=(Channel(ch=1, range=2 * V), Channel(ch=2, range=2 * V)),
                sample_interval=1 * us,
                pre_samples=PRE_SAMPLES,
                post_samples=CAPTURE_SAMPLES - PRE_SAMPLES,
                trigger=Edge(source=1, level=0.5 * V, direction="RISING", auto_ms=2000),
            )
        )

    def item_8_stop_and_close(self) -> list[str]:
        plug = self.open_plug()
        plug.stop()  # ps2000aStop, PG §3.65
        plug.tearDown()  # ps2000aStop and ps2000aCloseUnit, PG §3.65, §3.2; never raises
        return []


def _items(probe: Probe) -> list[tuple[str, Callable[[], list[str]]]]:
    return [
        ("1. Enumerate units (ps2000aEnumerateUnits)", probe.item_1_enumerate),
        ("2. Open and every ps2000aGetUnitInfo string", probe.item_2_open_and_info),
        ("3. ps2000aMaximumValue and ps2000aMinimumValue", probe.item_3_adc_limits),
        (
            "4. ps2000aGetTimebase2 for n = 0..10, 100, 1000, 10000 with one and two channels",
            probe.item_4_timebases,
        ),
        ("5. Every voltage range through ps2000aSetChannel", probe.item_5_ranges),
        ("6. Capture of 2000 samples per channel, no trigger", probe.item_6_capture_no_trigger),
        (
            "7. Capture with a RISING trigger at 0.5 V on channel A, auto 2000 ms",
            probe.item_7_capture_rising,
        ),
        ("8. ps2000aStop and ps2000aCloseUnit", probe.item_8_stop_and_close),
    ]


def _run_items(probe: Probe, report: Report) -> bool:
    """Run every item; returns True when item 2 opened a unit."""
    for title, item in _items(probe):
        notes: list[str] = []
        probe.rec.take()
        try:
            notes = item()
        except Exception as exc:  # the recorder logged driver failures; this records the rest
            notes = [f"item failed: {type(exc).__name__}: {exc}"]
        report.section(title, probe.rec.take(), notes)
    return probe.plug is not None


def main(
    argv: Sequence[str] | None = None,
    api: Ps2000aApi | None = None,
    stream: TextIO | None = None,
) -> int:
    """Run the probe; returns 0 when a unit was opened (item failures are in the report), else 1.

    `api` is a hook for tests: a `Ps2000aApi` (FakePs2000a) used instead of the real driver.
    `stream` defaults to the current ``sys.stdout``.
    """
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--serial", metavar="SER", help="serial number (default: $PICOSCOPE_SERIAL)"
    )
    parser.add_argument(
        "--out", default="dumps", help="report directory (default: dumps, git-ignored)"
    )
    args = parser.parse_args(argv)
    serial: str | None = args.serial or os.environ.get("PICOSCOPE_SERIAL") or None

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now()
    path = out_dir / f"probe-{started:%Y%m%d-%H%M%S}.md"
    report = Report(path, stream if stream is not None else sys.stdout)
    report.emit(f"# PicoScope 2000 (A API) probe {started:%Y-%m-%d %H:%M:%S}\n\n")
    report.emit(f"- report file: `{path}`\n- serial: `{serial or '(none)'}`\n")
    if serial is None:
        report.emit(
            "- WARNING: no --serial and no PICOSCOPE_SERIAL; the first unit found is opened "
            "(several PicoScopes may share this machine)\n"
        )
    report.emit("\n")

    recorder = Recorder(PicosdkApi() if api is None else api)  # PicosdkApi() imports nothing yet
    probe = Probe(recorder, serial)
    opened = False
    try:
        opened = _run_items(probe, report)
    finally:
        if probe.plug is not None:
            probe.plug.tearDown()  # idempotent, never raises; a no-op after item 8
            report.section("Teardown", recorder.take())
    if not opened:
        report.emit("RESULT: no unit was opened\n")
    return 0 if opened else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
