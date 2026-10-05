# picoscope-2000-openhtf

OpenHTF plug for PicoScope 2000 Series USB oscilloscopes that use the `ps2000a` driver (the "A API":
2205 MSO, 2206 to 2208 and 2405A to 2408B families), built on Pico's own ctypes wrapper `picosdk`.
Single-shot block capture on the analog channels: capture conditions are a frozen dataclass, a waveform is
the untouched ADC counts plus the metadata to recompute time and volts, and measurements are pure numpy
functions. Sibling of [rigol-dho-openhtf](https://github.com/pjaako/rigol-dho-openhtf) (same data-centred
API) and of the Siglent plugs (same process, a hardware-free fake, a README that records what the real
instrument does).

**Status: not verified on hardware.** Written against the programmer's guide and a fake driver only;
hardware session 1 (a PicoScope 2207B MSO) has not happened. Every behaviour the manual leaves open is an
`# ASSUMPTION(hw)` in the source and a question in `docs/api_reference.md`.

```python
import openhtf as htf
from picoscope_2000_openhtf import Capture, Channel, Edge, PicoScope2000Plug, measure
from picoscope_2000_openhtf.units import V, us

CAPTURE = Capture(channels=(Channel(ch=1, range=2 * V), Channel(ch=2, range=2 * V)), sample_interval=1 * us,
                  pre_samples=100, post_samples=1900, trigger=Edge(source=1, level=0.5 * V, auto_ms=1000))

@htf.measures(htf.Measurement('vpp_ch1').in_range(0.9, 1.1))
@htf.plug(scope=PicoScope2000Plug)
def phase(test, scope):
    scope.apply_capture(CAPTURE); scope.single(); scope.wait_ready()   # channels, timebase, trigger; arm; poll
    test.measurements.vpp_ch1 = measure.vpp(scope.read_waveform(1))    # volts in w.v, seconds in w.t
    scope.stop()
```

The plug has no setter per setting. `apply_capture` disables the unused channels, searches the timebase whose
sample interval is the smallest one not below the requested one (the real interval is in
`scope.sample_interval_s`), sets the trigger and registers the buffers. `tearDown()` stops any running
capture and closes only the handle this plug opened; it is idempotent and never raises, and afterwards every
method raises `RuntimeError("plug closed")`.

| method | behaviour |
|---|---|
| `apply_capture(capture)` | `SetChannel` for A..D, timebase search, `SetSimpleTrigger`, `SetDataBuffer`; raises `PicoError` on a bad status, `CaptureError` if the samples do not fit the memory |
| `single()` | `RunBlock` with the conditions of the last `apply_capture` |
| `wait_ready(timeout_s=None, poll_s=0.01)` | polls `IsReady`; on expiry stops the capture and raises `TimeoutError("capture not ready within X s")` |
| `read_waveform(ch)` | `Waveform(t, v, raw, meta)` of channel 1..4; one `GetValues` serves all channels |
| `stop()`, `ping()`, `flash_led(count=5)` | `Stop`, `PingUnit`, `FlashLed` (identify one of several scopes) |
| `PicoScope2000Plug.list_units()` | serials of the unopened units |

Measurements in `measure.py`: `vpp`, `vmean`, `vrms`, `vmin`, `vmax`, `frequency_hz`, `period_s`. They raise
`ClippedError` on data at full scale or with the driver's overflow bit set, unless `allow_clipped=True`.

## Setup

```bash
uv sync --all-extras --dev                          # Python 3.13, openhtf, picosdk, numpy, pytest, mypy, ruff
uv run pytest -q && uv run mypy                     # no hardware and no PicoSDK needed
uv run python example_test.py --fake                # the example on the fake driver, prints "example: PASS"
uv run python example_test.py --serial AQ005/139    # the example on a real unit, opened by serial number
PICOSCOPE_SERIAL=AQ005/139 uv run python tools/probe.py   # hardware probe, writes dumps/probe-<time>.md
```

`picosdk` does not bundle the native driver; `import picosdk.ps2000a` raises when the library is missing.
This package imports it lazily, on the first real driver call, so everything except real hardware runs
without it. Install the driver from Pico Technology on the machine that has the scope. **picotech.com is
blocked from the cloud agent sessions this project is developed in: download the driver on a normal machine
and read the vendor's current install steps there.** Linux x86 is the tested platform; Windows and macOS are
whatever `picosdk` loads the library on.

| OS | Native driver | Library the driver loads |
|---|---|---|
| Windows | the PicoSDK installer from picotech.com | `ps2000a.dll` |
| Linux | Pico's apt repository, package `libps2000a` (repository set-up steps on picotech.com) | `libps2000a.so` |
| macOS | the macOS download from picotech.com | `libps2000a.dylib` |

Selecting the unit. Several PicoScopes may share one machine, so open one by serial number: the constructor
argument `serial=`, else the OpenHTF config key `picoscope_2000_serial` (`CONF.load(picoscope_2000_serial=...)`
**after** importing the plug module; a key loaded earlier is lost), else the first unit found, which logs a
warning when more than one unit is connected. `tools/probe.py` reads the environment variable
`PICOSCOPE_SERIAL`. `picoscope_2000_timeout_s` (default 10.0) is the default for `wait_ready`.
`example_test.py --fake` runs the same phase on `FakePs2000a`, an in-memory driver whose signal is a 1 kHz,
1 V clock on every enabled channel; tests pass it as `PicoScope2000Plug(api=FakePs2000a())`.

## Models

The driver family is picked by the model, and the two families are incompatible. This plug is for the
`ps2000a` family only. The table is from `docs/research.md` (Pico's MATLAB driver READMEs and forum posts,
not yet checked against the datasheets).

| Model | Driver | Library | Tested |
|---|---|---|---|
| 2205 MSO, 2205A MSO | `ps2000a` | `libps2000a` | no |
| 2206A, 2206B (also MSO) | `ps2000a` | `libps2000a` | no |
| 2207A, 2207B (also MSO) | `ps2000a` | `libps2000a` | **2207B MSO only, and not yet** |
| 2208A, 2208B (also MSO) | `ps2000a` | `libps2000a` | no |
| 2405A | `ps2000a` | `libps2000a` | no |
| 2406B, 2407B, 2408B | `ps2000a` | `libps2000a` | no |
| 2204A, 2205A and the obsolete 2104, 2105, 2202, 2203, 2204, 2205 | `ps2000` (other API) | `libps2000` | not supported |

## Facts this is built on

From the PicoScope 2000 Series (A API) Programmer's Guide, ps2000apg.en-12 (`docs/`; "PG"). Nothing here is
measured yet.

- Block mode with one memory segment (PG §2.6.1.1): open the unit, `ps2000aSetChannel` per channel,
  `ps2000aGetTimebase2` until the wanted interval is found, trigger, `ps2000aRunBlock`, poll
  `ps2000aIsReady` (PG §3.26), `ps2000aSetDataBuffer` (PG §3.40), `ps2000aGetValues` (PG §3.18),
  `ps2000aStop`, `ps2000aCloseUnit`.
- A sample is a 16-bit count: full scale is `ps2000aMaximumValue()` (32 512 = 0x7F00), zero is 0, negative
  full scale is `ps2000aMinimumValue()` (-32 512) (PG §2.3), so `volts = raw * range / max_adc`. The range
  is set per channel, 20 mV to 20 V "subject to the device specification" (PG §2.3, §3.39); coupling AC or DC,
  both 1 Mohm.
- Memory is shared between the enabled channels, so unused channels are disabled explicitly; on MSO models
  the split also depends on the digital ports (PG §2.6.1).
- The sample interval comes from the timebase number `n` and the model's maximum rate; the manual has two
  tables, 500 MS/s and 1 GS/s models. `n = 0` is "available only in single-channel mode" (PG §2.7).
  `ps2000aGetTimebase2` returns the real interval in nanoseconds as a float and `maxSamples` (PG §3.14).
- `ps2000aRunBlock` takes pre- and post-trigger sample counts, the timebase, an unused `oversample` and a
  segment index; the total must fit the segment (PG §3.37). `ps2000aGetValues` before the scope is ready
  returns `PICO_NO_SAMPLES_AVAILABLE`; its `overflow` output is a bit field, bit 0 = channel A (PG §3.18).
- `ps2000aSetSimpleTrigger`: one channel, threshold in ADC counts, direction ABOVE, BELOW, RISING, FALLING
  or RISING_OR_FALLING, a delay in sample periods, `autoTrigger_ms` where 0 waits indefinitely (PG §3.56).
- `ps2000aOpenUnit(NULL)` opens the first unit, otherwise the one whose serial matches; handle -1 failed, 0
  none found, above 0 ok (PG §3.32). `ps2000aEnumerateUnits` lists only *unopened* units as a comma-separated
  string such as `AQ005/139,VDR61/356` (PG §3.4).
- Every function returns a `PICO_STATUS` from `PicoStatus.h`, and enum numbers are in `ps2000aApi.h`; the
  manual gives neither (PG §4.1, §4.2). The code uses names and resolves them through `picosdk`.

## Things the manual does not tell you

Nothing yet: hardware session 1 has not happened. Open questions are in `docs/api_reference.md`.

## Files

```
src/picoscope_2000_openhtf/
  __init__.py           package exports; the plug-side names load lazily so that the fake imports no openhtf or picosdk
  units.py              V, mV, s, ms, us, ns constants
  capture.py            Capture, Channel, Edge dataclasses, the range/channel/coupling/direction tables, validation
  driver.py             Ps2000aApi (the seam, one method per manual function) and PicosdkApi (the real ctypes adapter)
  plug.py               PicoScope2000Plug, Waveform, WaveformMeta, waveform_from_raw, PicoError, CaptureError
  measure.py            pure numpy measurements (vpp, vrms, frequency_hz, ...) and ClippedError
  fake_resource.py      FakePs2000a, the in-memory driver used by every hardware-free test (numpy only)
  py.typed              typing marker
tests/
  test_units.py         unit constants
  test_capture.py       capture validation and the range/trigger tables
  test_driver.py        PicosdkApi against a stub library: argument order and types, lazy import
  test_fake_resource.py the fake's rules, generated clock, defects, import isolation
  test_plug.py          the plug against the fake, including a real OpenHTF run
  test_measure.py       measurements on synthetic waveforms
  test_examples.py      example_test.py --fake and tools/probe.py against the fake
  test_import.py        importing the package never loads picosdk.ps2000a
example_test.py         minimal OpenHTF test, --fake or --serial SER
tools/probe.py          hardware probe run by the owner; every driver call goes to dumps/probe-<time>.md
docs/
  api_reference.md      the manual's subset this code uses, with the open questions for hardware
  picoscope-2000-series-a-api-programmers-guide.pdf   the manual (ps2000apg.en-12)
  picoscope-2000-series-a-api-programmers-guide.txt   its text dump for grep
  research.md           prior art and why this project exists
AGENTS.md SPEC.md HANDOFF.md   behaviour protocol, the contract, status and task board
.github/workflows/ci.yml       ruff, pytest, mypy on plain ubuntu
pyproject.toml uv.lock LICENSE .gitignore
```

## Licence

MIT. Use for anything; keep the copyright notice.
