# SPEC.md — phase 1: single-shot block capture on the analog channels

The real oscilloscope is NOT available to you. You code against
`picoscope_2000_openhtf.fake_resource.FakePs2000a` and the manual transcription
`docs/api_reference.md`. Section numbers `§x.y` below are sections of that
manual (ps2000apg.en-12). Where this file and `docs/api_reference.md`
disagree, the manual wins; say so in your report instead of guessing.

Concept: https://github.com/pjaako/rigol-dho-openhtf (the owner's scope plug).
Process and robustness conventions: the siglent siblings (`docs/research.md`).

## Facts from the manual

- General procedure (§2.2): open unit, set channels, set trigger, start
  capture, wait until ready, copy data to a buffer, stop, close.
- Block mode procedure with one memory segment (§2.6.1.1): OpenUnit,
  SetChannel per channel, GetTimebase (iterate until the wanted interval is
  found), trigger setup, RunBlock, wait with the BlockReady callback or poll
  IsReady, SetDataBuffer (may be done once after the trigger setup),
  GetValues, repeat RunBlock..GetValues as needed, Stop, CloseUnit.
- Memory is shared between enabled channels (§2.6.1); on MSO models the
  split also depends on the digital ports. Unused channels must therefore be
  disabled explicitly.
- Each sample is a 16-bit count; full-scale positive is the value returned
  by `ps2000aMaximumValue()` (32 512 = 0x7F00 per §2.3), zero is 0, full-scale
  negative is `ps2000aMinimumValue()` (–32 512). The voltage range is set per
  channel (§3.39); so `volts = raw * range_volts / max_adc`.
- Ranges (§3.39): ±20 mV, 50 mV, 100 mV, 200 mV, 500 mV, 1 V, 2 V, 5 V,
  10 V, 20 V, "subject to the device specification" (§2.3). Which of them
  the 2207B MSO offers is an open question; `ps2000aGetChannelInformation()`
  (§3.7) answers it on hardware.
- Coupling (§3.39): `PS2000A_AC`, `PS2000A_DC`, both 1 MΩ.
- Timebase (§2.7): the sample interval is a function of the timebase index
  `n` and the model's maximum sampling rate; two tables exist (500 MS/s and
  1 GS/s models); `n = 0` is "available only in single-channel mode"; "the
  fastest available sampling rate may depend on which channels are
  enabled". `ps2000aGetTimebase2()` (§3.14) returns the real interval
  (float ns) and `maxSamples` for a given `n` and the channels enabled by the
  last `SetChannel` calls; the manual says to iterate until the wanted
  interval is obtained.
- `ps2000aRunBlock()` (§3.37): pre- and post-trigger sample counts, timebase,
  `oversample` "not used", `timeIndisposedMs` out, segment index, callback
  pointer (NULL to poll). The total must not exceed the segment size.
- `ps2000aIsReady()` (§3.26): `ready` is 0 while collecting, non-zero when
  `GetValues` may be called.
- `ps2000aSetDataBuffer()` (§3.40): one int16 buffer per channel, with its
  length, segment, and ratio mode. `ps2000aGetValues()` (§3.18): start index,
  in/out number of samples, downsample ratio and mode (`PS2000A_RATIO_MODE_NONE`
  ignores the ratio), segment, out `overflow` bit field, bit 0 = channel A.
  "If multiple channels are enabled, a single call to this function is
  sufficient to retrieve data for all channels." Calling it before the scope
  is ready returns `PICO_NO_SAMPLES_AVAILABLE`.
- `ps2000aSetSimpleTrigger()` (§3.56): enable, source channel, threshold in
  ADC counts, direction (ABOVE, BELOW, RISING, FALLING, RISING_OR_FALLING),
  delay in sample periods, `autoTrigger_ms` (0 = wait indefinitely). One
  channel only; a small fixed hysteresis is included.
- `ps2000aOpenUnit()` (§3.32): out handle (–1 failed, 0 none found, > 0 ok),
  `serial` NULL for first unit found else the matching serial.
  `ps2000aEnumerateUnits()` (§3.4): count and a comma-separated list of
  serials of *unopened* units, e.g. `AQ005/139,VDR61/356`.
- `ps2000aGetUnitInfo()` (§3.17): info codes 0..10 (`PICO_DRIVER_VERSION`,
  `PICO_USB_VERSION`, `PICO_HARDWARE_VERSION`, `PICO_VARIANT_INFO`,
  `PICO_BATCH_AND_SERIAL`, `PICO_CAL_DATE`, `PICO_KERNEL_VERSION`,
  `PICO_DIGITAL_HARDWARE_VERSION`, `PICO_ANALOGUE_HARDWARE_VERSION`,
  `PICO_FIRMWARE_VERSION_1`, `PICO_FIRMWARE_VERSION_2`).
- Every function returns a `PICO_STATUS` from `PicoStatus.h` (§4.1); the
  manual lists per function which codes it returns. `picosdk.constants`
  mirrors that header (`PICO_STATUS`, `PICO_STATUS_LOOKUP`) and imports
  without the native library.
- Numeric values of enums (`PS2000A_*`) and status codes (`PICO_*`) are
  **not in the manual** (§4.1, §4.2 point to `PicoStatus.h` and
  `ps2000aApi.h`). The only mirror in this repository is `picosdk`
  (`picosdk.constants.PICO_STATUS`, `PICO_INFO`, and the enum dicts on the
  `ps2000a` library object, listed in `docs/api_reference.md`). Code uses
  names only and resolves them through picosdk at call time. Three manual
  sections spell the invalid-handle code `PICO_HANDLE_INVALID`; the header
  has only `PICO_INVALID_HANDLE`, which is what code and fake use.
- Analog offset (`analogOffset`, §3.39), MSO digital ports, rapid block,
  streaming, ETS, signal generator and advanced triggers are out of phase 1.

## Files

```
src/picoscope_2000_openhtf/
  __init__.py        exports PicoScope2000Plug, Waveform, WaveformMeta, Capture, Channel, Edge,
                     PicoError, CaptureError, ClippedError, __version__
  units.py           V, mV, s, ms, us, ns constants (floats), nothing else
  capture.py         Capture, Channel, Edge dataclasses; RANGES table; validation
  driver.py          Ps2000aApi Protocol (the seam) and PicosdkApi (the real adapter)
  plug.py            PicoScope2000Plug, Waveform, WaveformMeta, waveform_from_raw
  measure.py         pure numpy measurements
  fake_resource.py   FakePs2000a (implements Ps2000aApi), no imports from this package,
                     numpy only
tests/               see "Tests"
example_test.py      see below
tools/probe.py       hardware probe, owner-run only
README.md            see "README"
```

## 1. `units.py`

`V = 1.0`, `mV = 1e-3`, `s = 1.0`, `ms = 1e-3`, `us = 1e-6`, `ns = 1e-9`.
Used as `range=2 * V`, `sample_interval=1 * us`.

## 2. `capture.py`

All dataclasses are `@dataclass(frozen=True, kw_only=True)`, validated in
`__post_init__`, raising `ValueError` whose message lists **every** problem
found (one pass, `"; "`-joined), never only the first.

```python
RANGES: Mapping[float, str] = {  # PG §3.39, full-scale volts -> enum name
    20 * mV: "PS2000A_20MV",
    50 * mV: "PS2000A_50MV",
    100 * mV: "PS2000A_100MV",
    200 * mV: "PS2000A_200MV",
    500 * mV: "PS2000A_500MV",
    1 * V: "PS2000A_1V",
    2 * V: "PS2000A_2V",
    5 * V: "PS2000A_5V",
    10 * V: "PS2000A_10V",
    20 * V: "PS2000A_20V",
}
CHANNEL_NAMES: Mapping[int, str] = {
    1: "PS2000A_CHANNEL_A",
    2: "PS2000A_CHANNEL_B",
    3: "PS2000A_CHANNEL_C",
    4: "PS2000A_CHANNEL_D",
}  # PG §3.39
COUPLINGS: Mapping[str, str] = {"AC": "PS2000A_AC", "DC": "PS2000A_DC"}  # PG §3.39
DIRECTIONS: Mapping[str, str] = {
    d: f"PS2000A_{d}" for d in ("ABOVE", "BELOW", "RISING", "FALLING", "RISING_OR_FALLING")
}  # PG §3.56
```

Confirm the enum member names against `docs/api_reference.md` (the
`picosdk:` lines name the attribute holding each enum); if a name differs,
the reference wins and you report it.

- `Channel(ch: int, range: float, coupling: Literal["AC", "DC"] = "DC")`.
  `ch` in 1..4 (the plug maps 1 → A, like rigol-dho uses integers), `range`
  must be a key of `RANGES` (compare with `math.isclose`, rel 1e-9, then
  normalise to the key).
- `Edge(source: int, level: float, direction: Literal[...] = "RISING",
  auto_ms: int = 0, delay_samples: int = 0)`. `level` is volts; `auto_ms`
  0..32767 (int16 per §3.56), `delay_samples >= 0`.
- `Capture(channels: tuple[Channel, ...], sample_interval: float,
  pre_samples: int, post_samples: int, trigger: Edge | None = None)`.
  Rules: 1..4 channels with distinct `ch`; `sample_interval > 0`;
  `pre_samples >= 0`, `post_samples >= 0`, sum `> 0`; if `trigger` is set,
  its `source` is one of the channels and `abs(level) <= that channel's
  range`.
- `Capture.channel(ch) -> Channel` lookup, `Capture.enabled() -> tuple[int, ...]`.
- `Capture.trigger_threshold_adc(max_adc: int) -> int`:
  `round(level / range * max_adc)` for the source channel (§3.56 threshold is
  an ADC count; §2.3 scaling). Pure, testable.

## 3. `driver.py`

### 3.1 `Ps2000aApi` Protocol — the seam

One method per manual function used, **named exactly like the C function**,
arguments in the manual's order, Python types instead of pointers:
`in` arguments are parameters, `out` arguments are returned. Every method
returns `tuple[int, ...]` whose first element is the `PICO_STATUS` code; the
caller decides what to do with it. Enum arguments are passed as the
manual's **enum member names** (strings such as `"PS2000A_CHANNEL_A"`,
`"PS2000A_DC"`, `"PS2000A_1V"`, `"PS2000A_RISING"`,
`"PS2000A_RATIO_MODE_NONE"`); the adapter resolves them to integers, the
fake validates them against its own tables.

```python
class Ps2000aApi(Protocol):
    def ps2000aEnumerateUnits(self) -> tuple[int, int, str]: ...  # status, count, serials  PG §3.4
    def ps2000aOpenUnit(
        self, serial: str | None
    ) -> tuple[int, int]: ...  # status, handle          PG §3.32
    def ps2000aCloseUnit(self, handle: int) -> tuple[int]: ...  # PG §3.2
    def ps2000aGetUnitInfo(
        self, handle: int, info: str
    ) -> tuple[int, str]: ...  # info = "PICO_VARIANT_INFO" etc.  PG §3.17
    def ps2000aPingUnit(self, handle: int) -> tuple[int]: ...  # PG §3.35
    def ps2000aFlashLed(self, handle: int, start: int) -> tuple[int]: ...  # PG §3.5
    def ps2000aMaximumValue(self, handle: int) -> tuple[int, int]: ...  # PG §3.28
    def ps2000aMinimumValue(self, handle: int) -> tuple[int, int]: ...  # PG §3.30
    def ps2000aSetChannel(
        self, handle: int, channel: str, enabled: int, type: str, range: str, analogOffset: float
    ) -> tuple[int]: ...  # PG §3.39
    def ps2000aGetTimebase2(
        self, handle: int, timebase: int, noSamples: int, oversample: int, segmentIndex: int
    ) -> tuple[int, float, int]: ...  # status, timeIntervalNanoseconds, maxSamples  PG §3.14
    def ps2000aSetSimpleTrigger(
        self,
        handle: int,
        enable: int,
        source: str,
        threshold: int,
        direction: str,
        delay: int,
        autoTrigger_ms: int,
    ) -> tuple[int]: ...  # PG §3.56
    def ps2000aSetDataBuffer(
        self, handle: int, channel: str, buffer: npt.NDArray[np.int16], segmentIndex: int, mode: str
    ) -> tuple[int]: ...  # bufferLth = len(buffer)  PG §3.40
    def ps2000aRunBlock(
        self,
        handle: int,
        noOfPreTriggerSamples: int,
        noOfPostTriggerSamples: int,
        timebase: int,
        oversample: int,
        segmentIndex: int,
    ) -> tuple[int, int]: ...  # status, timeIndisposedMs; lpReady/pParameter always NULL  PG §3.37
    def ps2000aIsReady(self, handle: int) -> tuple[int, int]: ...  # status, ready  PG §3.26
    def ps2000aGetValues(
        self,
        handle: int,
        startIndex: int,
        noOfSamples: int,
        downSampleRatio: int,
        downSampleRatioMode: str,
        segmentIndex: int,
    ) -> tuple[int, int, int]: ...  # status, noOfSamples out, overflow  PG §3.18
    def ps2000aStop(self, handle: int) -> tuple[int]: ...  # PG §3.65
```

Check each signature against `docs/api_reference.md` before coding; if the
manual shows an argument this list lacks or orders differently, follow the
manual and report the difference.

### 3.2 `PicosdkApi(Ps2000aApi)` — the real adapter

- Constructor `PicosdkApi(lib: object | None = None)`. With `None`, the
  first call (not the constructor) does `from picosdk.ps2000a import
  ps2000a` and uses that object; the import error
  (`picosdk.errors.CannotFindPicoSDKError`) propagates with its own message.
  With a `lib` injected (tests), nothing is imported from picosdk except
  `picosdk.constants`.
- Each method builds the ctypes arguments (`c_int16`, `byref`, `create_string_buffer`,
  `buffer.ctypes.data_as(POINTER(c_int16))`, `len(buffer)` for `bufferLth`)
  exactly as the manual prototype requires and calls
  `getattr(lib, "<C function name>")`. Enum names are resolved through the
  enum dicts picosdk declares on the library object (the attribute names are
  in `docs/api_reference.md` `picosdk:` lines, e.g. `lib.PS2000A_CHANNEL[name]`);
  an unknown name raises `ValueError` before any call. Info codes for
  `GetUnitInfo` are resolved through `picosdk.constants.PICO_INFO` if it
  exists, else a module-level table copied from §3.17 with the citation.
- `GetUnitInfo`: call with a 256-byte string buffer, decode ASCII, strip the
  terminator.
- `EnumerateUnits`: 1024-byte buffer, `serialLth` in/out, return the string
  as the manual describes (comma-separated); the plug splits it.
- No status interpretation here. No retries. No sleeps.
- `status_name(code: int) -> str` module function using
  `picosdk.constants.PICO_STATUS_LOOKUP`, falling back to `f"0x{code:08X}"`.

### 3.3 Exceptions (defined in `plug.py`, re-exported from `__init__`)

- `PicoError(RuntimeError)`: attributes `function: str`, `status: int`,
  `name: str`; message `"<function> returned <name> (0x<code>)"`. Raised by the
  plug whenever a call does not return `PICO_OK`.
- `CaptureError(RuntimeError)`: `apply_capture` problems the driver did not
  reject (sample count above `maxSamples`, timebase search exhausted).
- `ClippedError(ValueError)`: raised by `measure.py` functions on clipped data.

## 4. `plug.py`

```python
class PicoScope2000Plug(BasePlug):  # type: ignore[misc]
    auto_placeholder = True

    def __init__(
        self,
        serial: str | None = None,
        *,
        api: Ps2000aApi | None = None,
        timeout_s: float | None = None,
    ) -> None: ...
```

- CONF keys, declared at import: `picoscope_2000_serial` (default `None`),
  `picoscope_2000_timeout_s` (default `10.0`). Precedence: constructor
  argument, then CONF, then default. `api=None` means `PicosdkApi()`.
- Constructor: `ps2000aEnumerateUnits` (log the count and serials at INFO;
  if `serial is None` and count > 1, log a WARNING naming the serials);
  `ps2000aOpenUnit(serial)`; a non-`PICO_OK` status raises `PicoError`; a
  `PICO_OK` with handle `<= 0` raises `PicoError` with the status name
  `"PICO_NOT_FOUND"`-equivalent message (use the manual's handle semantics in
  the text). Then `ps2000aGetUnitInfo` for the eleven info codes into
  `self.info: dict[str, str]` (code name → string; an info that returns
  `PICO_INFO_UNAVAILABLE` is stored as `""`, other errors raise), then
  `ps2000aMaximumValue`/`ps2000aMinimumValue` into `self.max_adc`,
  `self.min_adc`. Properties `serial` (from `PICO_BATCH_AND_SERIAL`) and
  `variant` (from `PICO_VARIANT_INFO`). If anything after `OpenUnit` fails,
  `CloseUnit` is called before re-raising.
- `list_units(api: Ps2000aApi | None = None) -> list[str]` static method:
  enumerate, split on `,`, drop empties.
- `apply_capture(capture: Capture) -> None`:
  1. For `ch` in 1..4: `ps2000aSetChannel(handle, name, enabled, coupling,
     range, 0.0)`; disabled channels are sent with `enabled=0`,
     `"PS2000A_DC"`, `"PS2000A_1V"`, `0.0` (the manual gives no "don't care"
     values; `# ASSUMPTION(hw): any valid coupling/range is accepted for a
     disabled channel`). A `PICO_INVALID_CHANNEL` status for a **disabled**
     channel 3 or 4 is tolerated (logged at INFO) and means the unit has
     two channels: record `self.channel_count` (4 by default, 2 then). Any
     other non-`PICO_OK`, and any failure for an enabled channel, raises
     `PicoError`. (`# ASSUMPTION(hw)`, open question 21.)
  2. Timebase search: estimate `n` from the 1 GS/s table of §2.7
     (`# ASSUMPTION(hw): 2207B MSO is a 1 GS/s model; the search below makes
     the result correct either way`): `n = 0,1,2` for 1, 2, 4 ns; else
     `n = round(interval_s * 125e6) + 2`. Call `ps2000aGetTimebase2(handle, n,
     total, 0, 0)`; if the returned interval (ns, converted to s) is below the
     requested one, increment `n`; if `n > 0` and the interval for `n - 1`
     would still be `>=` the requested one (query it), decrement. Accept the
     smallest `n` whose interval `>=` requested; cap the search at 64 calls,
     then raise `CaptureError`. A `PICO_INVALID_TIMEBASE` (or any
     non-`PICO_OK`) at the estimate means `n` is too small for the enabled
     channel count (e.g. `n = 0` with two channels, §2.7 footnote): increment
     and continue; any other status after that raises `PicoError`. The
     driver returns the interval as a C `float` (§3.14), so compare with
     `math.isclose(rel_tol=1e-6)` before `<`/`>=`.
  3. If `total > maxSamples` raise `CaptureError` naming both numbers.
  4. Trigger: with `Edge`, `ps2000aSetSimpleTrigger(handle, 1, source name,
     capture.trigger_threshold_adc(self.max_adc), direction name,
     delay_samples, auto_ms)`; without, `ps2000aSetSimpleTrigger(handle, 0,
     "PS2000A_CHANNEL_A", 0, "PS2000A_RISING", 0, 0)`
     (`# ASSUMPTION(hw): disabling with enable=0 ignores the other arguments`).
  5. Buffers: one `np.zeros(total, dtype=np.int16)` per enabled channel,
     `ps2000aSetDataBuffer(handle, name, buf, 0, "PS2000A_RATIO_MODE_NONE")`.
  6. Remember the resolved state: `self.capture`, `self.timebase`,
     `self.sample_interval_s` (from the driver, not the request),
     `self.max_samples`, buffers. Invalidate any cached waveforms.
  Nothing is sent if the `Capture` is invalid (the dataclass already
  guarantees that). The first failing call raises `PicoError`; log every call
  at DEBUG as `-> ps2000aSetChannel(...)` and the status as `<- PICO_OK`.
- `single() -> None`: requires `apply_capture` first (`RuntimeError`
  otherwise). `ps2000aRunBlock(handle, pre, post, timebase, 0, 0)`; store
  `self.time_indisposed_ms`; mark armed, clear cache.
- `wait_ready(timeout_s: float | None = None, poll_s: float = 0.01) -> None`:
  the rigol plug calls this `wait_stopped`; the manual's word is *ready*
  (§3.26). Poll `ps2000aIsReady` until `ready != 0`; `time.monotonic()`
  deadline from `timeout_s` or the plug's timeout; on expiry call
  `ps2000aStop` and raise `TimeoutError("no trigger within X s")`. Keep
  `time.sleep` and `time.monotonic` as module attributes so tests can
  monkeypatch them; tests never sleep for real.
- `read_waveform(ch: int) -> Waveform`: requires an armed-and-ready state
  (`RuntimeError` otherwise). On the first call after `single()`, one
  `ps2000aGetValues(handle, 0, total, 1, "PS2000A_RATIO_MODE_NONE", 0)` fills
  all buffers (§3.18); store `noOfSamples` returned and `overflow`. Return
  `waveform_from_raw(raw=buffer[:n].copy(), meta=...)` where
  `overflow` for this channel is `bool(overflow >> (ch - 1) & 1)`
  (§3.18: bit 0 = channel A). Further calls for other channels reuse the
  fetched data. Channel not enabled → `ValueError`.
- `stop() -> None`: `ps2000aStop`.
- `ping() -> None`: `ps2000aPingUnit`, raises `PicoError` if not `PICO_OK`.
- `flash_led(count: int = 5) -> None`: `ps2000aFlashLed(handle, count)`
  (§3.5 semantics; useful to identify one of several scopes).
- `tearDown()`: if open: `ps2000aStop` (ignore any error, log WARNING),
  `ps2000aCloseUnit` (same), mark closed. Idempotent, never raises. After it,
  every other public method raises `RuntimeError("plug closed")`.
- Logging: `self.logger`; INFO on open (serial, variant, driver version) and
  close, DEBUG per call, WARNING for teardown failures and the multi-unit
  case.

```python
class WaveformMeta(NamedTuple):
    channel: int
    range_v: float
    coupling: str
    max_adc: int
    sample_interval_s: float
    pre_samples: int
    timebase: int
    overflow: bool
    serial: str
    variant: str


class Waveform(NamedTuple):
    t: npt.NDArray[np.float64]  # seconds, t == 0 at the first post-trigger sample
    v: npt.NDArray[np.float64]  # volts
    raw: npt.NDArray[np.int16]  # untouched ADC counts
    meta: WaveformMeta


def waveform_from_raw(raw, meta) -> Waveform:
    t = (np.arange(len(raw)) - meta.pre_samples) * meta.sample_interval_s
    v = raw.astype(np.float64) * (meta.range_v / meta.max_adc)  # PG §2.3
```

`# ASSUMPTION(hw): the trigger point is sample index pre_samples` (§3.37
says the maximum number returned is pre + post; it does not say where the
trigger sample sits). Storage rule, as in rigol-dho: keep `raw` + `meta`,
recompute `t` and `v`.

## 5. `measure.py` (pure numpy, no plug import)

- `is_clipped(w: Waveform) -> bool`: `w.meta.overflow` or any `raw` at
  `±max_adc` (`>= max_adc` or `<= -max_adc`).
- `vpp(w, *, allow_clipped=False) -> float`, `vmean(w, ...)`,
  `vrms(w, ...)` (RMS of `v` as is, not AC-coupled), `vmin`, `vmax`.
- `frequency_hz(w, *, low=0.3, high=0.7, allow_clipped=False) -> float`:
  the rigol-dho algorithm: levels at the 5th/95th percentile of `v`, rising
  crossings detected with hysteresis (below `lo + low*(hi-lo)`, then above
  `lo + high*(hi-lo)`), frequency = (crossings - 1) / (time between first and
  last crossing); fewer than two crossings → `ValueError("not periodic")`.
- `period_s`, the inverse. Each function raises `ClippedError` when
  `is_clipped(w)` unless `allow_clipped=True`.

## 6. `fake_resource.py`

`FakePs2000a` implements `Ps2000aApi`. It imports only `numpy` and the
standard library (two tests enforce this: a subprocess import that asserts
no `picosdk`, `openhtf` or `picoscope_2000_openhtf` module is loaded, and an
`ast` check of its import statements).

- Constructor: `FakePs2000a(serials: Sequence[str] = ("FAKE0/001",),
  variant: str = "2207BMSO", signal: Literal["clock", "ramp"] = "clock",
  clock_hz: float = 1000.0, clock_v: float = 1.0, defect: Literal["shift",
  "gain", "glitch"] | None = None, memory_samples: int = 65536,
  max_rate_hz: float = 1e9, ready_after: int = 2)`.
  `# ASSUMPTION(hw)` on `memory_samples`, `max_rate_hz` and the ranges
  offered; the owner corrects them after hardware session 1.
- Public attributes: `log: list[tuple[str, tuple[object, ...]]]` (function
  name and the arguments as passed), `reject: dict[str, str]` mapping a
  function name to a `PICO_*` status name to return instead of `PICO_OK`
  (one-shot or sticky? sticky, until the test clears it), `units: dict[int,
  FakeUnit]` by handle, `closed_handles: list[int]`.
- Status codes: a module-level table `STATUS: Mapping[str, int]` with the
  codes the fake needs (`PICO_OK = 0x0`, `PICO_NOT_FOUND`, `PICO_INVALID_HANDLE`,
  `PICO_INVALID_CHANNEL`, `PICO_INVALID_VOLTAGE_RANGE`, `PICO_INVALID_COUPLING`,
  `PICO_INVALID_TIMEBASE`, `PICO_INVALID_PARAMETER`, `PICO_NO_SAMPLES_AVAILABLE`,
  `PICO_INVALID_INFO`, `PICO_INFO_UNAVAILABLE`, `PICO_TOO_MANY_SAMPLES`,
  `PICO_BUSY`, `PICO_INVALID_TRIGGER_CHANNEL`) with values copied from
  `picosdk.constants.PICO_STATUS` by the coder and cited `# PicoStatus.h via
  picosdk.constants`. The plug compares codes by name through `status_name`,
  so the fake and `picosdk` must agree; `tests/test_fake_resource.py` asserts
  equality against `picosdk.constants.PICO_STATUS` for every entry.
- Behaviour, each rule cited from the manual:
  - `EnumerateUnits` lists unopened serials (§3.4). `OpenUnit(None)` opens
    the first unopened; `OpenUnit(serial)` opens that one or returns
    `(PICO_NOT_FOUND, 0)`; handles start at 1 and are never reused.
  - Every other call with an unknown or closed handle returns
    `PICO_INVALID_HANDLE`.
  - `GetUnitInfo` returns deterministic strings per info name
    (`PICO_VARIANT_INFO` → `variant`, `PICO_BATCH_AND_SERIAL` → the serial,
    `PICO_DRIVER_VERSION` → `"0.0.0.0-fake"`, ...); unknown name →
    `PICO_INVALID_INFO`.
  - `MaximumValue` → 32512, `MinimumValue` → –32512 (§2.3).
  - `SetChannel` validates the enum names (`PICO_INVALID_CHANNEL`,
    `PICO_INVALID_COUPLING`, `PICO_INVALID_VOLTAGE_RANGE`) and stores the
    channel state; `channel C/D` on a two-channel variant →
    `PICO_INVALID_CHANNEL` (`# ASSUMPTION(hw)`).
  - `GetTimebase2`: the 1 GS/s table of §2.7 at `max_rate_hz = 1e9`
    (`n=0,1,2 → 1, 2, 4 ns`; `n>=3 → (n-2)/125e6`); `n = 0` with more than one
    channel enabled → `PICO_INVALID_TIMEBASE` (§2.7 footnote);
    `maxSamples = memory_samples // max(1, enabled_count)` rounded as §2.6.1
    (two → half, three or four → quarter); `noSamples > maxSamples` →
    `PICO_TOO_MANY_SAMPLES` with the values still filled in.
  - `SetSimpleTrigger` validates names, stores state; source not enabled →
    `PICO_INVALID_TRIGGER_CHANNEL` (`# ASSUMPTION(hw)`).
  - `SetDataBuffer` stores the numpy array by channel (it must write into
    that array later, not a copy).
  - `RunBlock`: `pre + post > maxSamples` → `PICO_TOO_MANY_SAMPLES`; a
    channel enabled without a buffer is allowed here (the manual registers
    buffers at step 7). Stores pre/post/timebase, sets `polls_left =
    ready_after`, returns `timeIndisposedMs = ceil(total * interval * 1e3)`.
  - `IsReady`: `ready = 0` while `polls_left > 0` (decrementing), then 1.
    When nothing is running the manual does not say what happens; return
    `(PICO_OK, 0)` and flag `# ASSUMPTION(hw)`.
  - `GetValues`: before ready → `PICO_NO_SAMPLES_AVAILABLE` (§3.18). Else for
    each enabled channel with a buffer: generate the signal, convert to
    counts with that channel's range (`round(v / range * 32512)`), clip to
    ±32512 and set the channel's overflow bit (bit 0 = A, §3.18) if clipping
    occurred, write into the registered array, return `noOfSamples =
    min(requested, total)`. The trigger is honoured: with a RISING trigger
    on a channel carrying the clock, sample index `pre` is the first sample
    at or above the threshold after being below it; FALLING likewise; without
    a trigger the phase is fixed at 0. `defect="shift"` adds `0.1 * clock_v`
    DC; `"gain"` multiplies by 1.1; `"glitch"` replaces one sample at
    `pre + 7` by full scale. `signal="ramp"` is `i % 1000 / 1000 * clock_v`.
    The time axis used for generation is `(i - pre) * interval`, so a
    1 kHz clock sampled at 1 µs has a period of 1000 samples; the clock is a
    square wave between `0` and `clock_v` (`# measured later on hardware
    against the SDG`).
  - `Stop`: clears the armed state, keeps the data (§2.6.1 "Data retention").
  - `CloseUnit`: forgets the handle, the serial becomes unopened again.
  - `FlashLed`, `PingUnit`: logged, `PICO_OK`.
  - Every method first appends to `log`, then checks `reject`.

## 7. Tests (`tests/`, pytest, no hardware, no sleeps, no network)

- `test_import.py` (exists): keep green.
- `test_units.py`: trivial.
- `test_capture.py`: every validation rule, the all-errors-at-once message,
  `RANGES` keys equal the manual's ten ranges, `trigger_threshold_adc`
  examples (`level = range → 32512`, `0 → 0`, `-range/2 → -16256`).
- `test_driver.py`: `PicosdkApi(lib=_StubLib())` where `_StubLib` has the
  enum dicts and callables that record ctypes arguments and write into
  pointers; assert argument order/types per manual prototype for
  `ps2000aOpenUnit`, `ps2000aSetChannel`, `ps2000aGetTimebase2`,
  `ps2000aSetDataBuffer` (pointer is the numpy buffer's address, length is
  `len`), `ps2000aGetValues`, `ps2000aGetUnitInfo`; unknown enum name raises
  `ValueError` without calling the lib; `PicosdkApi()` with no lib does not
  import picosdk until first use (check `sys.modules`); `status_name`.
- `test_fake_resource.py`: open/close/enumerate semantics, every status
  rule above, the generated clock (period, amplitude, trigger alignment),
  overflow on clipping, defects, `STATUS` equals `picosdk.constants.PICO_STATUS`,
  import isolation (subprocess + `ast`).
- `test_plug.py`: with a `_plug(**kw)` helper that builds the fake and the
  plug and clears `fake.log` after the constructor. Assert exact `log`
  sequences for the constructor, `apply_capture` (channel order 1..4,
  disabled channels, timebase search calls, trigger, buffers), `single`,
  `wait_ready` (monkeypatched `time`), `read_waveform` (one `GetValues` for
  two channels), `stop`, `tearDown` (idempotent, swallows `reject`), closed
  plug raises. Conversions: `v` of the fake clock has `vpp ≈ clock_v`,
  `frequency_hz ≈ clock_hz` at several `sample_interval`s and ranges;
  `t[pre_samples] == 0`; `waveform_from_raw` round trip; `overflow` bit per
  channel; `PicoError` carries function and status name; `CaptureError`
  on `total > maxSamples`; `TimeoutError` calls `Stop`; multi-unit WARNING;
  CONF precedence; `list_units`. One real `htf.Test(...).execute()`
  integration test with a `FakePlug` subclass.
- `test_measure.py`: synthetic sine/square arrays (build `Waveform` by
  hand), `frequency_hz` within 0.1 % for ≥ 10 periods, `vpp`, `vrms` of a
  sine (`A/√2`), `ClippedError`, `allow_clipped`.
- `test_examples.py`: `example_test.py --fake` exits 0 and prints
  `example: PASS`; importing `example_test` and `tools.probe` opens no unit
  (fake log empty / no `PicosdkApi` constructed).

## 8. `example_test.py`

Root of the repo. Declares `CAPTURE = Capture(channels=(Channel(ch=1, range=2 * V),
Channel(ch=2, range=2 * V)), sample_interval=1 * us, pre_samples=100,
post_samples=1900, trigger=Edge(source=1, level=0.5 * V, auto_ms=1000))`. One
OpenHTF phase with `@htf.plug(scope=PicoScope2000Plug)` and
`@htf.measures(vpp_ch1 in range 0.9..1.1 V, freq_ch1 in range 990..1010 Hz,
num_points == 2000, vpp_ch2 with no limit)`; the fake puts its clock on
every enabled channel, so both channels pass. Flow: `apply_capture`, `single`,
`wait_ready`, `read_waveform(1)`, `read_waveform(2)`, measurements via
`measure.py`, `stop`. Flags: `--fake` (uses a `FakePlug(PicoScope2000Plug)`
subclass injecting `FakePs2000a()`), `--serial SER` (sets CONF after the
import). Prints `example: PASS` or `example: FAIL`, exits 0/1. The hardware
limits above are hypotheses for a 1 kHz, 1 Vpp square from the SDG;
mark them `# ASSUMPTION(hw)`.

## 9. `tools/probe.py` (owner-run, hardware)

`main(argv, api=None, stream=sys.stdout)`. Takes `--serial` or
`PICOSCOPE_SERIAL`. Writes `dumps/probe-<timestamp>.md` incrementally (git-
ignored). Numbered `item_N` methods that never raise, each recording the
calls made (a `Recorder` wrapping the api logs name, arguments and status):
1 enumerate units; 2 open and all `GetUnitInfo` strings; 3 `MaximumValue`/
`MinimumValue`; 4 `GetTimebase2` for `n = 0..10` and `n = 100, 1000, 10000`
with one channel then two channels enabled (reports interval and
`maxSamples` → answers the 500 MS/s vs 1 GS/s question and the memory
split); 5 every range in `RANGES` via `SetChannel` (which are accepted);
6 one capture of 2000 samples per channel with no trigger, print min/max
raw and the overflow bits; 7 the same with a RISING trigger at 0.5 V on
channel A and `auto_ms=2000`, print the raw values around index `pre`;
8 `Stop`, `Close`. `--risky` gate not needed (nothing risky on a scope).
Importing the module must not open a unit.

## 10. README

Title and one-paragraph lead, a bold **Status** line, a ten-line usage
snippet first (plug in an OpenHTF phase with the `Capture` from the example),
then Setup (uv install; native driver per OS: Windows PicoSDK installer,
Linux Pico apt repository, macOS download, each with the library name the
driver loads: `ps2000a.dll`, `libps2000a.so`, `libps2000a.dylib`; Linux x86
is the tested platform), "Facts this is built on" (from the manual, cited),
"Things the manual does not tell you" (empty until hardware session 1, with
the heading present), Files, Licence. No badges. Models table: the ps2000a
models from `docs/research.md`, with "tested only on 2207B MSO".

## Documentation limits

- Do not invent API behaviour. If the manual is silent, implement the
  simplest reading, mark `# ASSUMPTION(hw)`, mirror it in the fake, and add
  the question to `docs/api_reference.md` "Open questions" if it is missing.
- Do not add features beyond this file (no streaming, rapid block, digital
  ports, signal generator, YAML, golden comparison).
- No model identifiers anywhere in the repository.

## Done means

- `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest -q`,
  `uv run mypy` all clean; `uv run python example_test.py --fake` prints
  `example: PASS`.
- Every `ps2000a*` identifier in `src/` appears in `docs/api_reference.md`
  (grep both ways: `grep -o 'ps2000a[A-Za-z0-9]*' -r src | sort -u` must be a
  subset of the reference).
- Every `PS2000A_*` / `PICO_*` name in `src/` appears in
  `docs/api_reference.md` or in `picosdk.constants`.
- Every `# ASSUMPTION(hw)` in `src/` has a matching item in
  `docs/api_reference.md` "Open questions for hardware verification".
- `tests/test_import.py` still proves `picosdk.ps2000a` is not imported.
- `HANDOFF.md` task board updated by the owner.

## Required report (from each coder agent)

Commands run with their final output lines; files created or changed; every
place where the manual and this SPEC disagreed and what you did; every
`# ASSUMPTION(hw)` you added; anything you could not do.
