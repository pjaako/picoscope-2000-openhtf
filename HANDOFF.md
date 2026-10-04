# HANDOFF

Status for a cold agent. Keep this current at every commit.

## Done
- 2026-10-04 Prior-art research (`docs/research.md`): no existing plug; concept follows rigol-dho-openhtf (scope plug), process follows the siglent siblings; build on `picosdk` (official ctypes wrapper), driver split ps2000 vs ps2000a by model. `pypicosdk` (new official OO wrapper) checked: no 2000 Series support, not usable.

## In flight
- Waiting on the user's answers to the requirements questions (exact model, driver, capture modes, Python/OS targets, sig-gen, MSO). `AGENTS.md`, `SPEC.md`, `docs/api_reference.md` are not written yet and must not be written before the Programmer's Guide is in `docs/`.

## Blocked on hardware
- Everything. No hardware has been touched. The cloud session cannot reach picotech.com (proxy 403); the Programmer's Guide PDF must be committed by the user and the native driver installed on a local machine.

## Out of scope for now
- Undecided until the questions are answered.
