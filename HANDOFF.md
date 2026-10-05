# HANDOFF

Status for a cold agent. Keep this current at every commit.

## Done
- 2026-10-04 Prior-art research (`docs/research.md`): no existing plug; concept follows rigol-dho-openhtf (scope plug), process follows the siglent siblings; build on `picosdk` (official ctypes wrapper); `pypicosdk` has no 2000 Series support.
- 2026-10-05 Requirements answered by the user: PicoScope **2207B MSO** (ps2000a driver, A API manual committed to `docs/`), phase 1 = single-shot block capture on analog channels, API as close to rigol-dho as the driver allows, channels as integers 1..4, Python 3.13, all OSes supported with Linux x86 as the test platform, several scopes per machine (open by serial), dependency `picosdk` from PyPI.
- 2026-10-05 T0 packaging skeleton, CI, `tests/test_import.py` (c17beb6).
- 2026-10-05 `AGENTS.md`, `SPEC.md` (phase 1 contract).
- 2026-10-05 D1 `docs/api_reference.md` (manual transcription, 84 flagged notes, 20 open hardware questions); T1 units/capture/measure (531563b).
- 2026-10-05 T2 driver seam + picosdk adapter (d1c9074); T3 fake driver (b4e4b20); open questions 21..29 added.
- 2026-10-05 T4 plug + tests (d5a7d49); T5 example_test.py, tools/probe.py, README (2ba9b5c).
- 2026-10-05 R1 review by a stronger agent (two blocking findings: buffer lifetime, timebase search) and fix-up round (6134566). 519 tests, five gates green, example passes in fake mode. Phase 1 code is complete up to the hardware gate.

## Task board
| id | task | owner | state |
|---|---|---|---|
| T0 | packaging skeleton, CI, import test | coder | done |
| D1 | `docs/api_reference.md` transcription + picosdk cross-check | writer agent | done |
| T1 | `units.py`, `capture.py`, `measure.py` + tests | coder | done |
| T2 | `driver.py` (Protocol + PicosdkApi) + `tests/test_driver.py` | coder | done |
| T3 | `fake_resource.py` + `tests/test_fake_resource.py` | coder | done |
| T4 | `plug.py` + `tests/test_plug.py` (incl. htf integration) | coder | done |
| T5 | `example_test.py`, `tools/probe.py`, `tests/test_examples.py`, README | coder | done |
| R1 | review of T1..T5 against SPEC and manual by a stronger agent, fix-up round | reviewer + coder | done |
| STOP | hardware session 1 on the user's Linux machine (owner + user) | human gate | **next** |
| H1 | `SPEC-hardware-1.md` work order from the probe dump, fake and README corrections, replay oracle | owner | after STOP |

## In flight
- Nothing. The next step needs the instrument (see below).

## Blocked on hardware
- All `# ASSUMPTION(hw) Qn` markers in `src/`, `tools/` and `example_test.py`, i.e. open questions 1..35 in `docs/api_reference.md`. The cloud session cannot reach picotech.com (proxy 403) and has no native driver; hardware session 1 runs on the user's local Linux x86 machine.

## Hardware session 1: procedure for a cold agent on the local machine

You act as the project owner (AGENTS.md roles); the user is present and the 2207B MSO is on USB. Read `AGENTS.md`, `SPEC.md`, `README.md`, and `docs/api_reference.md` "Open questions for hardware verification" first. Work on a branch `hardware-session-1` off the current branch. Nothing on a scope input is dangerous, but stop and close the unit in `finally:` always.

1. **Environment.** `uv sync --all-extras --dev`; `uv run pytest -q` must pass (519). Install the native driver from Pico's Linux download page (picotech.com, the `libps2000a` package of Pico's apt repository; `docs/research.md` names it, the exact apt commands are on Pico's page). Check: `uv run python -c "import picosdk.ps2000a"` must import without error, and `lsusb` must show the Pico device. If the import fails with `CannotFindPicoSDKError`, the library is not on the loader path (`ldconfig -p | grep ps2000a`). Record the driver and library versions in the dump.
2. **Identify the unit.** `uv run python -c "from picoscope_2000_openhtf import PicoScope2000Plug; print(PicoScope2000Plug.list_units())"`. Several PicoScopes may be attached; export `PICOSCOPE_SERIAL=<the 2207B MSO serial>` and confirm with `flash_led`.
3. **Probe.** `uv run python tools/probe.py` (reads `PICOSCOPE_SERIAL`, or `--serial`). It writes `dumps/probe-<timestamp>.md` (git-ignored). Items: 1 enumerate, 2 unit info, 3 ADC limits, 4 timebase table with one and two channels plus `nMaxSamples`, 5 accepted ranges, 6 untriggered capture with `raw % 256` statistics, 7 triggered capture with channel A at 0.5 V, 8 stop/close. For item 7 the station's SDG must feed a 1 kHz, 1 Vpp square (0 to 1 V) into channel A and B; the SPD stays off. Do not edit the probe to make an item pass; record what happened.
4. **Answer the open questions.** Go through `docs/api_reference.md` items 1..35 with the dump. For each answered item write the fact (with the dump timestamp) into README "Things the manual does not tell you" (observation, conditions, date, consequence), and into `SPEC-hardware-1.md` as numbered facts F1..Fn (the sibling format: "The real oscilloscope is NOT available to you", "Facts measured", per-file rules, "Done means"). Items that stay open are listed as such.
5. **Example on hardware.** `uv run python example_test.py --serial $PICOSCOPE_SERIAL` with the SDG signal as above. Expected `example: PASS`. On FAIL, decide from the waveform whether the plug, the fake's assumption, or the example's limits are wrong; the README findings log decides, not the test.
6. **Fix-up by work order.** Delegate the fake and plug corrections to a coder agent against `SPEC-hardware-1.md` (coder agents never touch the hardware). Every fact goes into the fake, made at least as strict as the device; the matching `# ASSUMPTION(hw) Qn` marker is replaced by `# measured, hardware session 1 (README)`. Add `tests/data/hardware_session_1.txt` (the probe's call/status transcript) and a replay test that the fake reproduces every status and every shape of every reply, as the siblings do. Re-run the probe and the example afterwards.
7. **Commit** with the trailers the harness provides, update this file (Done, board, Blocked), set the README status line, and open a pull request to merge into the main branch.

Decision points that need the user: the Linux driver install (root), which SDG channel feeds which scope input, and whether to keep `picosdk` from PyPI (1.1) if a function turns out to be missing or wrong (then pin a GitHub commit of picosdk-python-wrappers and record why in `docs/research.md`).

## Out of scope for now
- Analog offset, MSO digital ports, rapid block, streaming, ETS, signal generator/AWG, advanced triggers, YAML capture files, golden-waveform comparison (phase 2 candidates: signal generator, rapid block, digital ports).
