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

## Reference concept (the owner's own plugs)

- https://github.com/pjaako/siglent-sdg-openhtf (complete, hardware-verified):
  `src/` layout, hatchling, `uv`, Python 3.13, thin `BasePlug` with an
  injectable transport, hand-written fake that logs calls and models state,
  pytest against the fake only, `example_test.py --fake`, `tools/probe.py`,
  `tests/data/hardware_session_1.txt` replay oracle, mypy strict, CI on
  ubuntu.
- https://github.com/pjaako/siglent-spd-openhtf (newer process documents):
  `AGENTS.md`, `SPEC.md` with a "Done means" checklist, committed
  `HANDOFF.md`, `docs/<protocol>_reference.md` transcribed from the manual
  with an "Open questions for hardware verification" section,
  `# ASSUMPTION(hw):` markers, ruff + mypy.
- https://github.com/pjaako/rigol-dho-openhtf: the original scope plug both
  siblings name as the file-naming reference. Not cloned yet; it is the
  closest instrument class (an oscilloscope) and should be read before
  `SPEC.md` is written.

This project follows the spd conventions where they are newer and the sdg
code where spd has none yet. The transport seam becomes a *driver* protocol
(ctypes function table) instead of a VISA resource, and the fake becomes a
fake driver that models handle, channels, timebase, trigger and buffers.

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
