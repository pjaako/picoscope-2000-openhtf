"""Minimal OpenHTF test using the PicoScope 2000 Series (A API) plug.

Usage:
    python example_test.py --fake               # no hardware: the plug on an in-memory fake driver
    python example_test.py --serial AQ005/139   # a real unit, opened by serial number

The hardware limits below assume a 1 kHz, 1 Vpp square wave from the station's signal generator on
channels 1 and 2 (channel 1 triggers). Without --serial the first unit found is opened; the plug
logs a warning when several are connected. The serial can also be set once for the whole station
with the OpenHTF config key picoscope_2000_serial.
"""

import argparse
import sys
from collections.abc import Sequence
from typing import Any

import openhtf as htf
from openhtf.util import units

from picoscope_2000_openhtf import Capture, Channel, Edge, PicoScope2000Plug, measure
from picoscope_2000_openhtf.fake_resource import FakePs2000a
from picoscope_2000_openhtf.plug import CONF
from picoscope_2000_openhtf.units import V, us

# Capture conditions as data: two channels at +-2 V, 1 us per sample, 100 samples before and 1900
# after a rising edge through 0.5 V on channel 1; the trigger gives up after one second
# (PG §3.39, §3.56).
CAPTURE = Capture(
    channels=(Channel(ch=1, range=2 * V), Channel(ch=2, range=2 * V)),
    sample_interval=1 * us,
    pre_samples=100,
    post_samples=1900,
    trigger=Edge(source=1, level=0.5 * V, auto_ms=1000),
)


# ASSUMPTION(hw): the limits assume a 1 kHz, 1 Vpp square wave from the station's signal generator
# on channels 1 and 2; the owner confirms or corrects them in hardware session 1 (the fake's clock
# is the same signal, see SPEC section 6).
@htf.plug(scope=PicoScope2000Plug)
@htf.measures(
    htf.Measurement("vpp_ch1").with_units(units.VOLT).in_range(0.9, 1.1),
    htf.Measurement("freq_ch1").with_units(units.HERTZ).in_range(990, 1010),
    htf.Measurement("num_points").equals(2000),
    htf.Measurement("vpp_ch2").with_units(units.VOLT),
)
def capture_phase(test: Any, scope: PicoScope2000Plug) -> None:
    """Capture both channels once and record Vpp, frequency and the number of points."""
    scope.apply_capture(CAPTURE)  # channels, timebase search, trigger and buffers
    scope.single()  # arm one block capture
    scope.wait_ready()  # poll until the trigger fired (or the auto-trigger timeout passed)
    w1 = scope.read_waveform(1)  # one GetValues serves both channels
    w2 = scope.read_waveform(2)
    test.measurements.vpp_ch1 = measure.vpp(w1)  # ClippedError on over-range data
    test.measurements.freq_ch1 = measure.frequency_hz(w1)
    test.measurements.num_points = len(w1.v)
    test.measurements.vpp_ch2 = measure.vpp(w2)
    scope.stop()


class FakePlug(PicoScope2000Plug):
    """The plug on an in-memory fake driver, for runs without hardware."""

    def __init__(self) -> None:
        super().__init__(api=FakePs2000a())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--fake", action="store_true", help="use the fake driver (no hardware)")
    parser.add_argument("--serial", metavar="SER", help="serial number of the unit to open")
    args = parser.parse_args(argv)
    if args.serial:
        # After importing the plug module: a key loaded before it is declared is lost.
        CONF.load(picoscope_2000_serial=args.serial)
    phase = capture_phase.with_plugs(scope=FakePlug) if args.fake else capture_phase
    passed = bool(htf.Test(phase).execute(test_start=lambda: "example_dut"))
    print("example: PASS" if passed else "example: FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
