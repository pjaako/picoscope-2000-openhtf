# HANDOFF

Status for a cold agent. Keep this current at every commit.

## Done
- 2026-10-04 Prior-art research (`docs/research.md`): no existing plug; concept follows rigol-dho-openhtf (scope plug), process follows the siglent siblings; build on `picosdk` (official ctypes wrapper); `pypicosdk` has no 2000 Series support.
- 2026-10-05 Requirements answered by the user: PicoScope **2207B MSO** (ps2000a driver, A API manual committed to `docs/`), phase 1 = single-shot block capture on analog channels, API as close to rigol-dho as the driver allows, channels as integers 1..4, Python 3.13, all OSes supported with Linux x86 as the test platform, several scopes per machine (open by serial), dependency `picosdk` from PyPI.
- 2026-10-05 T0 packaging skeleton, CI, `tests/test_import.py` (c17beb6).
- 2026-10-05 `AGENTS.md`, `SPEC.md` (phase 1 contract).

## Task board
| id | task | owner | state |
|---|---|---|---|
| T0 | packaging skeleton, CI, import test | coder | done |
| D1 | `docs/api_reference.md` transcription + picosdk cross-check | writer agent | in flight |
| T1 | `units.py`, `capture.py`, `measure.py` + tests | coder | in flight |
| T2 | `driver.py` (Protocol + PicosdkApi) + `tests/test_driver.py` | coder | waiting on D1 |
| T3 | `fake_resource.py` + `tests/test_fake_resource.py` | coder | waiting on D1 |
| T4 | `plug.py` + `tests/test_plug.py` (incl. htf integration) | coder | waiting on T1..T3 |
| T5 | `example_test.py`, `tools/probe.py`, `tests/test_examples.py`, README | coder | waiting on T4 |
| R1 | review of T1..T5 against SPEC and manual by a stronger agent | reviewer | waiting on T5 |
| STOP | hardware session 1 on the user's Linux machine (owner + user) | human gate | blocked |

## In flight
- D1 and T1 (see board). Owner integrates each result, runs the four checks, commits with the task id.

## Blocked on hardware
- All `# ASSUMPTION(hw)` items and `docs/api_reference.md` "Open questions". The cloud session cannot reach picotech.com (proxy 403) and has no native driver; hardware session 1 runs on the user's local Linux x86 machine with `tools/probe.py`, `PICOSCOPE_SERIAL` set.

## Out of scope for now
- Analog offset, MSO digital ports, rapid block, streaming, ETS, signal generator/AWG, advanced triggers, YAML capture files, golden-waveform comparison (phase 2 candidates: signal generator, rapid block, digital ports).
