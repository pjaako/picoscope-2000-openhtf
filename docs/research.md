# Prior-art research (2026-10-04)

Question: does an OpenHTF plug or a reusable Python driver for PicoScope 2000
Series USB oscilloscopes already exist, and what can be borrowed?

## Verdict

- No OpenHTF plug for any PicoScope exists in public (GitHub repository and
  code search, PyPI, Pico forum). This is a new build.
- Unlike the Siglent siblings, the instrument has no SCPI port. Pico ships a C
  shared library per driver family and the only official Python access is a
  ctypes wrapper. The plug therefore wraps a C API, not a VISA resource.
- The 2000 Series is split across **two incompatible driver APIs**, each with
  its own Programmer's Guide. Which one applies depends on the exact model:

  | Driver | Native library | Models |
  |---|---|---|
  | `ps2000` ("PicoScope 2000 Series Programmer's Guide") | `ps2000.dll` / `libps2000.so` | 2204A, 2205A (and obsolete 2104, 2105, 2202, 2203, 2204, 2205) |
  | `ps2000a` ("PicoScope 2000 Series (A API) Programmer's Guide") | `ps2000a.dll` / `libps2000a.so` | 2206/2207/2208 (A and B, incl. MSO), 2205 MSO, 2205A MSO, 2405A, 2406B, 2407B, 2408B |

  Source: Pico's MATLAB instrument-driver READMEs and forum posts (the PDFs
  themselves could not be fetched from the cloud session, see below). The
  mapping must be confirmed against the Programmer's Guide placed in this
  folder before any code relies on it.
- The function names, enums, status codes and call sequences must come from
  the Programmer's Guide in this folder. Nothing is to be taken from the
  siblings' SCPI references, from `pico-python`, or from forum snippets
  without checking it against that guide.

## Official Python wrapper: `picosdk`

- https://github.com/picotech/picosdk-python-wrappers, ISC licence, active
  (commits in September/October 2026). PyPI `picosdk` 1.1 (2022) lags master
  by years; depends only on `numpy`.
- One module per driver (`picosdk.ps2000`, `picosdk.ps2000a`). Each module
  declares the C functions by name with `ctypes` argument/return types
  (`make_symbol`) and the enums from the C header. It is a 1:1 mirror of the
  Programmer's Guide, which makes manual cross-checking straightforward.
- Native libraries are not bundled. Windows: PicoSDK installer. Linux: Pico's
  apt repository (`libps2000a`, `libps2000`). macOS: separate download.
- **Importing `picosdk.ps2000a` or `picosdk.ps2000` raises
  `CannotFindPicoSDKError` when the native library is absent** (verified in
  this session on Linux without the SDK). `picosdk.discover` imports both and
  fails the same way. `picosdk`, `picosdk.functions`, `picosdk.constants`,
  `picosdk.errors` import fine. Consequence: the plug must import the driver
  module lazily, and tests must run without it (CI is plain ubuntu).
- Library loading goes through one class, `picosdk.library.Library`
  (`find_library` + `CDLL`/`WinDLL`), a natural seam for a fake.
- Examples in the repo (`ps2000aExamples/`, `ps2000Examples/`) show block,
  rapid-block, streaming and signal-generator call sequences. They are
  illustrations only; the guide decides.

## Official next-generation wrapper: `pypicosdk` (checked 2026-10-04)

- https://github.com/picotech/pyPicoSDK, PyPI `pypicosdk` 1.7.5 (2026-08),
  ISC licence, Python >=3.10, maintained by Pico Technology. Object-oriented
  API (`scope = psdk.ps6000a(); scope.open_unit()`), still needs PicoSDK
  installed separately.
- **Supports only the 6000E (`ps6000a`), 3000E and 5000E (`psospa`) and
  5000D (`ps5000a`) series.** The package tree has no `ps2000` or `ps2000a`
  module and the README lists no 2000 Series model. It cannot drive a
  PicoScope 2000 and is not a candidate dependency.
- Worth reading for the shape of a Pythonic layer over the C API (unit
  open/close, channel setup, block capture, streaming, error list), since it
  is Pico's own view of how the ctypes calls should be wrapped.

## Unofficial wrapper: `pico-python`

- https://github.com/colinoflynn/pico-python, PyPI `picoscope` 0.7.32
  (2025-12), BSD-2-Clause, Python >=3.9. Higher-level API (set channel,
  timebase, trigger, run block, read volts) with classes `PS2000` and
  `PS2000A`. No streaming; `PS2000` has no pre-trigger and no open-by-serial.
- Useful to read for structure (timebase tables, ADC-to-volt conversion), not
  as a dependency: it hides the C API we need to cite, and its tables are not
  the manual.

## Reference concept: rigol-dho-openhtf (the owner's own scope plug)

https://github.com/pjaako/rigol-dho-openhtf (MIT, Python >=3.12) is the
concept this plug follows, because both are oscilloscope plugs. What carries
over, in words (the Pico driver has no SCPI, so nothing transfers literally):

- **Data-centred API.** The package exports one plug class and one
  `Waveform` type. `Waveform` is a NamedTuple of float64 numpy arrays in SI
  units (`t`, `v`), the untouched `raw` ADC samples, and the metadata needed
  to recompute `t` and `v` from `raw`. `t = 0` is the trigger point. Stored
  data is raw plus metadata, never float arrays.
- **Capture conditions are typed data**, not setters: frozen keyword-only
  dataclasses (`Capture`, `Channel`, `Edge`) with `Literal` choices validated
  in `__post_init__`, one source of truth for the allowed values, every
  problem reported in one pass. A YAML front end with a generated JSON Schema
  exists; it is optional for a first version.
- **Capture flow is explicit primitives**: apply the capture conditions
  (validate everything first, send nothing on error, read back, raise once
  listing every mismatch), arm a single acquisition, poll until stopped with
  a timeout (`TimeoutError`), read the waveform. The PicoScope equivalent is
  arm a block, poll ready, fetch buffers, convert ADC counts to volts.
- **Measurements are Python functions** on the waveform (Vpp, frequency with
  percentile levels and hysteresis), validated against an independent oracle
  on hardware. The scope's own measurement engine was only ever an oracle;
  the PicoScope has none, so the Python path is the only one.
- **The fake generates deterministic waveforms** (a bounded 1 kHz clock, or
  counter patterns), uses non-zero offsets so a missing conversion term fails
  a test, injects named defects (`shift`, `gain`, `glitch`), models the
  arm/wait/stop state machine, and copies measured hardware quirks in with
  dated comments, made harsher than the real instrument.
- **Clipped data is refused** where a verdict depends on it (raw at 0 or the
  top code).
- **Golden-waveform comparison** (`golden.py`, mask-based verdict) is an
  optional later phase.
- **tearDown** restores saved state, stops, closes only handles the plug
  opened, never shared ones. For a scope nothing is dangerous; stop and
  close is enough.
- **README is the measurement log**: "Facts this is built on", "Things the
  manual does not tell you (firmware ...)" with observation, conditions,
  date, consequence, and explicit "not yet understood" subsections.
- **AGENTS.md** is a flat bullet list; later `SPEC-*.md` files are full work
  orders that start with "The real oscilloscope is NOT available to you",
  then "Facts measured", per-file rules, and "Done means".

Not carried over from rigol-dho (the siglent siblings do these better):
unguarded, non-idempotent tearDown and constructor; no transport Protocol;
SCPI literals without manual citations; no CI, no ruff, partial mypy; no
status file in git; no probe tool; no hardware-transcript oracle. The full
comparison is in the owner's session notes (RIGOL_DHO_REFERENCE.md, not
committed).

## Process conventions: the siglent siblings

- https://github.com/pjaako/siglent-sdg-openhtf (complete, hardware-verified):
  `src/` layout, hatchling, `uv`, Python 3.13, thin `BasePlug` with an
  injectable transport Protocol, guarded idempotent `tearDown`, constructor
  cleanup on failure, pytest against the fake only, `example_test.py --fake`,
  `tools/probe.py`, `tests/data/hardware_session_1.txt` replay oracle, mypy
  strict, CI on ubuntu.
- https://github.com/pjaako/siglent-spd-openhtf (newer process documents):
  `AGENTS.md`, `SPEC.md` with a "Done means" checklist, committed
  `HANDOFF.md`, `docs/<protocol>_reference.md` transcribed from the manual
  with an "Open questions for hardware verification" section,
  `# ASSUMPTION(hw):` markers, ruff + mypy.

This project takes the API concept from rigol-dho and the process and
robustness conventions from the siglent siblings. The transport seam becomes
a *driver* protocol (ctypes function table) instead of a VISA resource, and
the fake becomes a fake driver that models handle, channels, timebase,
trigger, buffers and generates waveforms.

## Projects worth borrowing structure from (structure only, no API details)

| Project | Licence | What to borrow |
|---|---|---|
| https://github.com/picotech/picosdk-python-wrappers | ISC | the dependency itself; `assert_pico_ok`, `adc2mV` helpers; example call order as a reading aid |
| https://github.com/Svinninge/mcp-picoscope | not stated | the idea of a ctypes mock backend for hardware-free tests of a `ps2000` device |
| https://github.com/colinoflynn/pico-python | BSD-2 | shape of a Pythonic layer over the C API; where it works around 2000-series quirks (e.g. 2206B serial string) |
| https://github.com/umi-eng/openhtf-instruments | MIT | monorepo CI shape; not needed if the sibling CI is reused |

Not to be copied: anything whose licence is not stated (mcp-picoscope code),
GPL projects, and all command tables of the Siglent siblings.

## Cloud session constraints found

- `www.picotech.com` and `labs.picotech.com` are blocked by the session's
  egress proxy. The Programmer's Guide PDF and the native driver cannot be
  downloaded here; the PDF has to be committed to `docs/` by the user, and
  hardware runs happen on a local machine.
- PyPI and GitHub are reachable. `picosdk 1.1` and `openhtf 1.6.1` install on
  Python 3.11 here; Python 3.13 is the target per the siblings.
