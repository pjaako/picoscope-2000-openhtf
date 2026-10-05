This file is the only source of truth for ps2000a API details in this repository. Transcribed from docs/picoscope-2000-series-a-api-programmers-guide.pdf (ps2000apg.en-12). Code agents cite it as `# PG §3.39` (manual section number) next to every driver call, enum and constant. If something you need is not here, stop and say so; do not take it from other projects, picosdk examples or memory.

# ps2000a API reference (PicoScope 2207B MSO, single-shot block mode, analog channels)

Scope of this file: the subset of the PicoScope 2000 Series (A API) Programmer's Guide (edition ps2000apg.en-12, Pico Technology, 2022; the guide itself says "SDK version: 10.6.12" on p. 7) needed for a plug that discovers units, opens one by serial number, and runs single-shot block-mode captures on the analog channels of a PicoScope 2207B MSO with the ps2000a driver.

## Conventions used in this file

- Section numbers (`§3.39`) and page numbers (`p. 76`) are the manual's own. Printed page numbers equal PDF page numbers (the PDF has no front-matter offset).
- C prototypes and code blocks are copied line for line from the text dump of the manual, including the manual's own typos (for example missing commas between parameters). Do not "fix" them.
- Prose (argument meanings, notes) is the manual's wording; lines that the PDF wraps are joined onto one line. Nothing is paraphrased unless the line starts with `⚠`.
- `⚠ manual note:` marks an ambiguity, typo or contradiction in the manual. The manual's text is quoted, never silently corrected.
- `⚠ transcription note:` marks a place where the PDF cannot be reproduced in plain text (superscripts, merged table cells).
- `picosdk:` lines and `⚠ picosdk mismatch:` lines are the only non-manual information in this file. They come from the Python package `picosdk` 1.1 (`picosdk/ps2000a.py`) and are a cross-check only; they are not API documentation. See "picosdk 1.1 notes" at the end.
- The "Dir" column in Arguments tables is derived from the manual's own words ("on entry", "on exit", "output:", "input:"). Arguments passed by value are `in`. For a pointer argument whose direction the manual does not state, the column says `not stated`.
- `2^32` is written for the manual's "2" with superscript "32" (the text dump of the PDF flattens it to "232").
- The manual contains NO numeric values for the enumerated types `PS2000A_CHANNEL`, `PS2000A_COUPLING`, `PS2000A_RANGE`, `PS2000A_THRESHOLD_DIRECTION`, `PS2000A_RATIO_MODE`, `PS2000A_TIME_UNITS`, `PS2000A_CHANNEL_INFO`, nor for any `PICO_STATUS` code (the only numbers the manual gives are: the digital ports `0x80`/`0x81`, the `PICO_INFO` codes 0 to 10, and the digital values of `PS2000A_EXT_MIN_VALUE` / `PS2000A_EXT_MAX_VALUE`, which are –32 767 / +32 767 in §2.3). The manual says (§4.1, §4.2, p. 119) these live in `PicoStatus.h` and `ps2000aApi.h`, which are not part of this repository. See "Open questions for hardware verification".

---

# Part 1. Concepts

### §2.1 Driver (p. 10)

Your application will communicate with a PicoScope 2000 (A API) driver called ps2000a.dll, which is supplied in 32-bit and 64-bit versions. The driver exports the ps2000a function definitions in standard C format, but this does not limit you to programming in C. You can use the API with any programming language that supports standard C calls.

The API driver depends on another DLL, picoipp.dll (which is supplied in 32-bit and 64-bit versions) and a low-level driver called WinUsb.sys. These are installed by the SDK and configured when you plug the oscilloscope into each USB port for the first time. Your application does not call these drivers directly.

Related text from §3 (p. 30): "All functions are C functions using the standard call naming convention (__stdcall). They are all exported with both decorated and undecorated names."

⚠ manual note: the manual names only Windows binaries (`ps2000a.dll`, `picoipp.dll`, `WinUsb.sys`) and lists only Windows operating systems in §1.2 (p. 8: "Windows 7, 8 or 10"). It says nothing about the name of the driver library on Linux or macOS.

### §2.2 General procedure (p. 10)

A typical program for capturing data consists of the following steps:

1. Open the scope unit.
2. Set up the input channels with the required voltage ranges and coupling type.
3. Set up triggering.
4. Start capturing data. (See Sampling modes, where programming is discussed in more detail.)
5. Wait until the scope unit is ready.
6. Copy data to a buffer.
7. Stop capturing data.
8. Close the scope unit.

Many example programs are available on GitHub. These demonstrate how to use the functions of the driver software in each of the modes available.

### §2.3 Voltage ranges (p. 11)

**Analog input channels**

You can set a device input channel to any voltage range from ±20 mV to ±20 V (subject to the device specification) with ps2000aSetChannel(). Each sample is scaled to 16 bits, and the minimum and maximum values returned to your application are given by ps2000aMinimumValue() and ps2000aMaximumValue() as follows:

| Function | Voltage | Value returned, decimal | Value returned, hex |
|---|---|---|---|
| ps2000aMaximumValue() | maximum | 32 512 | 7F00 |
|  | zero | 0 | 0000 |
| ps2000aMinimumValue() | minimum | –32 512 | 8100 |

**Example** (the manual shows this as a figure; the numbers below are the figure's labels)

1. Call ps2000aSetChannel() with range set to PS2000A_1V.
2. Apply a sine wave input of 500 mV amplitude to the oscilloscope.
3. Capture some data using the desired sampling mode.
4. The data will be encoded as shown opposite.

| Voltage level in the figure | Hex | Decimal |
|---|---|---|
| +1 V | 7F00 | +32 512 |
| +500 mV | 3F80 | +16 256 |
| 0 V | 0000 | 0 |
| –500 mV | C080 | –16 256 |
| –1 V | 8100 | –32 512 |

**External trigger input (PicoScope 2206, 2207 and 2208 only)**

The external trigger input (marked EXT) is scaled to a 16-bit value as follows:

| Voltage | Constant | Digital value |
|---|---|---|
| –5 V | PS2000A_EXT_MIN_VALUE | –32 767 |
| 0 V |  | 0 |
| +5 V | PS2000A_EXT_MAX_VALUE | +32 767 |

Model-specific range lists: the manual has none in §2.3. The only range information in the manual is (a) the sentence above ("from ±20 mV to ±20 V (subject to the device specification)"), (b) the list of `range` values under ps2000aSetChannel() (§3.39: `PS2000A_20MV` to `PS2000A_20V`), and (c) the run-time query ps2000aGetChannelInformation() (§3.7).

⚠ manual note: there is no mention of the PicoScope 2207B or 2207B MSO anywhere in §2.3. The external-trigger paragraph says "(PicoScope 2206, 2207 and 2208 only)"; the manual does not say whether "2207" there includes the 2207B / 2207B MSO.

⚠ manual note: the manual gives no formula for converting an ADC count to volts. It gives only the table and the ±1 V example above. The `Value returned` of ps2000aMaximumValue()/ps2000aMinimumValue() is ±32 512, while the external trigger input is scaled to ±32 767.

### §2.5 Triggering (p. 13) (overview only)

PicoScope oscilloscopes can either start collecting data immediately or be programmed to wait for a trigger event.

For simple trigger setups, call this single function:

· ps2000aSetSimpleTrigger()

For more complex trigger setups, call the three individual trigger functions:

· ps2000aSetTriggerChannelConditions()
· ps2000aSetTriggerChannelDirections()
· ps2000aSetTriggerChannelProperties()

A trigger event can occur when one of the signal or trigger input channels crosses a threshold voltage on either a rising or a falling edge. It is also possible to combine two inputs using the logic trigger function.

To set up pulse width, delay and dropout triggers, you can also call the pulse width qualifier function:

· ps2000aSetPulseWidthQualifier()

### §2.6 Sampling modes (p. 14) (intro)

PicoScope 2000 Series oscilloscopes can run in various sampling modes.

· Block mode. In this mode, the scope stores data in internal buffer memory and then transfers it to the PC. When the data has been collected it is possible to examine the data, with an optional downsampling factor. The data is lost when a new run is started in the same segment, the settings are changed, or the scope is powered down.

· ETS mode. In this mode, it is possible to increase the effective sampling rate of the scope when capturing repetitive signals. It is a modified form of block mode.

· Rapid block mode. This is a variant of block mode that allows you to capture more than one waveform at a time with a minimum of delay between captures. You can use downsampling in this mode if you wish.

· Streaming mode. In this mode, data is passed directly to the PC without being stored in the scope's internal buffer memory. This enables long periods of data collection for chart recorder and data-logging applications. Streaming mode supports downsampling and triggering, while providing fast streaming at typical rates of 1 to 10 MS/s, as specified in the data sheet for your device.

In all sampling modes, the driver returns data asynchronously using a callback. This is a call to one of the functions in your own application. When you request data from the scope, you pass to the driver a pointer to your callback function. When the driver has written the data to your buffer, it makes a callback (calls your function) to signal that the data is ready. The callback function then signals to the application that the data is available.

Because the callback is called asynchronously from the rest of your application, in a separate thread, you must ensure that it does not corrupt any global variables while it runs.

For compatibility with programming environments not supporting C-style callback functions, polling of the driver is available in block mode.

### §2.6.1 Block mode (p. 15)

In block mode, the computer prompts a PicoScope 2000 Series oscilloscope to collect a block of data into its internal memory. When the oscilloscope has collected the whole block, it signals that it is ready and then transfers the whole block to the computer's memory through the USB port.

· Block size. The maximum number of values depends upon the size of the oscilloscope's memory. The memory buffer is shared between the enabled channels, so if two channels are enabled, each receives half the memory, and if three or four channels are enabled, each receives a quarter of the memory. This partitioning is handled transparently by the driver. The block size also depends on the number of memory segments in use – see ps2000aMemorySegments().

  Note: The PicoScope MSO models behave differently. If only the two analog channels or only the two digital ports are enabled, each receives half the memory. If any combination of one or two analog channels and one or two digital ports is enabled, each receives a quarter of the memory.

· Sampling rate. A PicoScope 2000 Series oscilloscope can sample at different rates according to the selected timebase and the combination of enabled channels. See the Timebases section for the specifications that apply to your scope model.

· Setup time. The driver normally performs a number of setup operations, which can take up to 50 milliseconds, before collecting each block of data. If you need to collect data with the minimum time interval between blocks, use rapid block mode and avoid calling setup functions between calls to ps2000aRunBlock(), ps2000aStop() and ps2000aGetValues().

· Downsampling. When the data has been collected, you can set an optional downsampling factor and examine the data. Downsampling is a process that reduces the amount of data by combining adjacent samples. It is useful for zooming in and out of the data without having to repeatedly transfer the entire contents of the scope's buffer to the PC.

· Memory segmentation. The scope's internal memory can be divided into segments so that you can capture several waveforms in succession. Configure this using ps2000aMemorySegments().

· Data retention. The data is lost when a new run is started in the same segment, the settings are changed, or the scope is powered down.

See Using block mode for programming details.

⚠ manual note: the memory-sharing note for MSO models does not say what happens when exactly one analog channel is enabled and no digital port is enabled (the first sentence of the Block size bullet says only "if two channels are enabled, each receives half the memory"). §3.29 ps2000aMemorySegments() states the division differently (see there).

### §2.6.1.1 Using block mode (p. 16)

This is the general procedure for reading and displaying data in block mode using a single memory segment:

Note: Use the * steps when using the digital ports on MSO models.

1. Open the oscilloscope using ps2000aOpenUnit().
2. Select channel ranges and AC/DC coupling using ps2000aSetChannel().
2*. Set the digital port using ps2000aSetDigitalPort().
3. Using ps2000aGetTimebase(), select timebases until the required nanoseconds per sample is located.
4. Use the trigger setup functions ps2000aSetTriggerChannelConditions(), ps2000aSetTriggerChannelDirections() and ps2000aSetTriggerChannelProperties() to set up the trigger if required.
4*. Use the trigger setup functions ps2000aSetTriggerDigitalPortProperties() and ps2000aSetTriggerChannelConditions() to set up the digital trigger if required.
5. Start the oscilloscope running using ps2000aRunBlock().
6. Wait until the oscilloscope is ready using the ps2000aBlockReady() callback (or poll using ps2000aIsReady()).
7. Use ps2000aSetDataBuffer() to tell the driver where your memory buffer is. (For greater efficiency when doing multiple captures, you can call this function outside the loop, after step 4.)
8. Transfer the block of data from the oscilloscope using ps2000aGetValues().
9. Display the data.
10. Repeat steps 5 to 9.
11. Stop the oscilloscope using ps2000aStop().
12. Request new views of stored data using different downsampling parameters. See Retrieving stored data.
13. Call ps2000aCloseUnit().

⚠ manual note: step 4 lists the three advanced trigger functions; ps2000aSetSimpleTrigger() (§3.56) is the single-call alternative named in §2.5. The numbered procedure itself does not mention ps2000aSetSimpleTrigger().

⚠ manual note: step 7 comes after step 6 (RunBlock, wait) in the numbered list, but the parenthesis says the call can be made "outside the loop, after step 4", i.e. before ps2000aRunBlock(). The manual does not say which order is required. ps2000aSetDataBuffer() (§3.40) states only: "tells the driver where to store the data ... that will be returned after the next call to one of the ps2000aGetValues...() functions."

⚠ manual note: step 12 ("Request new views of stored data") comes after step 11 (ps2000aStop()), while §3.65 says of block mode: "you can optionally call ps2000aStop() to terminate the current capture. Any data in the buffer will be invalid." The manual does not reconcile these.

### §2.6.1.2 Asynchronous calls in block mode (p. 17)

To avoid blocking the calling thread when calling ps2000aGetValues(), it is possible to call ps2000aGetValuesAsync() instead. This immediately returns control to the calling thread, which then has the option of waiting for the data or calling ps2000aStop() to abort the operation.

Callback variant versus polling variant (both statements are from the manual, in the places named):

- Callback: ps2000aRunBlock() argument `lpReady`, "a pointer to the ps2000aBlockReady() callback function that the driver will call when the data has been collected." (§3.37, p. 72); see §3.1.
- Polling: "To use the ps2000aIsReady() polling method instead of a callback function, set this pointer to NULL." (§3.37, p. 72); "This function may be used instead of a callback function to receive data from ps2000aRunBlock(). To use this method, pass a NULL pointer as the lpReady argument to ps2000aRunBlock(). You must then poll the driver to see if it has finished collecting the requested samples." (§3.26, p. 61)

### §2.6.5 Retrieving stored data (p. 27)

You can collect data from the ps2000a driver with a different downsampling factor when ps2000aRunBlock() or ps2000aRunStreaming() has already been called and has successfully captured all the data. Use ps2000aGetValuesAsync().

### §2.7 Timebases (p. 28)

The ps2000a API allows you to select any of 2^32 different timebases based on the maximum sampling rate† of your oscilloscope. The timebases allow slow enough sampling in block mode to overlap the streaming sample intervals, so that you can make a smooth transition between block mode and streaming mode. Calculate the timebase using ps2000aGetTimebase().

⚠ transcription note: in the PDF the exponent in "2^32", "2^n" and "3 to 2^32–1" is a superscript; the text dump shows "232", "2n" and "232–1". The values in the "sample interval values" column confirm the reading (for example n = 2: 2^2 / 500,000,000 = 8 ns).

**500 MS/s maximum sampling rate models:**

| timebase (n) | sample interval formula | sample interval values |
|---|---|---|
| 0 | 2^n / 500,000,000 | 2 ns* |
| 1 | 2^n / 500,000,000 | 4 ns |
| 2 | 2^n / 500,000,000 | 8 ns |
| 3 to 2^32–1 | (n – 2) / 62,500,000 | 3 => 16 ns; ...; 2^32–1 => ~ 69 s |

**1 GS/s maximum sampling rate models:**

| timebase (n) | sample interval formula | sample interval values |
|---|---|---|
| 0 | 2^n / 1,000,000,000 | 1 ns* |
| 1 | 2^n / 1,000,000,000 | 2 ns |
| 2 | 2^n / 1,000,000,000 | 4 ns |
| 3 to 2^32–1 | (n – 2) / 125,000,000 | 3 => 8 ns; ...; 2^32–1 => ~ 34 s |

**PicoScope 2205 MSO:**

| timebase (n) | sample interval formula | sample interval values |
|---|---|---|
| 0 | 2^n / 200,000,000 | 0 => 5 ns** |
| 1 | n / 100,000,000 | 10 ns |
| 2 | n / 100,000,000 | 20 ns |
| 3 to 2^32–1 | n / 100,000,000 | 3 => 30 ns; ...; 2^32–1 => ~ 43 s |

⚠ transcription note: in the PDF the formula cells are merged across rows (one "2^n / 500,000,000" cell spans timebases 0 to 2; one "(n – 2) / 62,500,000" cell spans 3 to 2^32–1; for the 2205 MSO one "n / 100,000,000" cell spans timebases 1 to 3 and beyond). They are repeated per row above.

† The fastest available sampling rate may depend on which channels are enabled, and on the sampling mode. Refer to the oscilloscope data sheet for sampling rate specifications. In streaming mode the sampling rate may additionally be limited by the speed of the USB port.

\* Available only in single-channel mode.

\*\* Not available when channel B active, nor when channel A and both digital ports active.

**ETS mode**

In ETS mode the sample time is not set according to the above tables but is instead calculated and returned by ps2000aSetEts().

⚠ manual note: the manual never says which of the two tables ("500 MS/s maximum sampling rate models" or "1 GS/s maximum sampling rate models") applies to the PicoScope 2207B MSO. The only model named in the timebase tables is the PicoScope 2205 MSO. The 2207B MSO appears in the manual only in the model list of §1.1 (p. 7), where the 2207B MSO is listed under "2-channel MSO".

⚠ manual note: the tables do not state the unit of the "sample interval formula" column; the values column shows ns or s, consistent with seconds (for example 2^0 / 500,000,000 s = 2 ns).

⚠ manual note: the rule for how many channels may be enabled at the fastest timebases is only the footnote `*` ("Available only in single-channel mode.") on timebase 0 of the 500 MS/s and 1 GS/s tables, plus footnote `†` ("The fastest available sampling rate may depend on which channels are enabled, and on the sampling mode."), plus §2.6.1 ("A PicoScope 2000 Series oscilloscope can sample at different rates according to the selected timebase and the combination of enabled channels."). Footnote `**` (2205 MSO) is the only rule mentioning digital ports. The manual does not say whether timebases 1 and 2 of the 500 MS/s and 1 GS/s tables have a channel restriction. Per §3.13 the result of ps2000aGetTimebase() "depends on the number of channels enabled by the last call to ps2000aSetChannel()".

### §2.9 Combining oscilloscopes (p. 29)

It is possible to collect data using up to 64 PicoScope 2000 Series oscilloscopes at the same time, subject to the capabilities of the PC. Each oscilloscope must be connected to a separate USB port. The ps2000aOpenUnit() function returns a handle to an oscilloscope. All the other functions require this handle for oscilloscope identification. For example, to collect data from two oscilloscopes at the same time:

```text
   CALLBACK ps2000aBlockReady(...)
   // define callback function specific to application

   handle1 = ps2000aOpenUnit()
   handle2 = ps2000aOpenUnit()

   ps2000aSetChannel(handle1)

   // set up unit 1
   ps2000aSetDigitalPort(handle1) // only when using MSO
   ps2000aRunBlock(handle1)

   ps2000aSetChannel(handle2)

   // set up unit 2
   ps2000aSetDigitalPort(handle2) // only when using MSO
   ps2000aRunBlock(handle2)

   // data will be stored in buffers
   // and application will be notified using callback

   ready = FALSE
   while not ready
      ready = handle1_ready
      ready &= handle2_ready
```

⚠ manual note: this pseudo-code is not the C signature. It calls `ps2000aOpenUnit()` with no arguments and uses its return value as the handle, while the prototype in §3.32 is `PICO_STATUS ps2000aOpenUnit(int16_t * handle, int8_t * serial)`. It also omits all arguments of ps2000aSetChannel() and ps2000aRunBlock(). Do not copy it as code. Two consecutive `ps2000aOpenUnit()` calls without a serial open "the first scope found" per §3.32; the manual does not say whether the second call would skip the already-opened unit, although §3.4 says ps2000aEnumerateUnits() "does not detect units that already have a handle assigned to them by the driver".


---

# Part 2. API functions (in scope)

Introduction from §3 (p. 30): "The ps2000a API exports a number of functions for you to use in your own applications. All functions are C functions using the standard call naming convention (__stdcall). They are all exported with both decorated and undecorated names."

## Device discovery, open, close, information

### §3.4 ps2000aEnumerateUnits() – find all connected oscilloscopes (p. 33)

```c
   PICO_STATUS ps2000aEnumerateUnits
   (
     int16_t    * count,
     int8_t     * serials,
     int16_t    * serialLth
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `* count` | out | on exit, the number of ps2000a units found. |
| `* serials` | out | on exit, a list of serial numbers separated by commas and terminated by a final null.<br>Example: AQ005/139,VDR61/356,ZOR14/107<br>Can be NULL on entry if serial numbers are not required. |
| `* serialLth` | in/out | on entry, the length of the char buffer pointed to by serials; on exit, the length of the string written to serials |

**Returns**

- `PICO_OK`
- `PICO_BUSY`
- `PICO_NULL_PARAMETER`
- `PICO_FW_FAIL`
- `PICO_CONFIG_FAIL`
- `PICO_MEMORY_FAIL`
- `PICO_CONFIG_FAIL_AWG`
- `PICO_INITIALISE_FPGA`

**Notes**

- Applicability: All modes.
- This function counts the number of unopened PicoScope 2000 Series (A API) units connected to the computer and returns a list of serial numbers as a string. It does not detect units that already have a handle assigned to them by the driver.
- ⚠ manual note: the manual does not say how large the `serials` buffer must be, nor what status is returned when `serialLth` is too small (no "buffer too small" code is listed under Returns), nor whether the length written on exit includes the final null.
- ⚠ manual note: the format of the serial number string is shown only by the example "AQ005/139,VDR61/356,ZOR14/107". ps2000aGetUnitInfo() `PICO_BATCH_AND_SERIAL` (§3.17) has the example "KJL87/006". The manual does not state that the strings are identical or that either is the string ps2000aOpenUnit() `serial` expects, although §3.32 calls it "the serial number of the scope to be opened".

picosdk: ps2000a.ps2000aEnumerateUnits, argtypes = [c_void_p, c_char_p, c_void_p], restype = c_uint32 (the same ctypes function object is also set as ps2000a._EnumerateUnits)

### §3.32 ps2000aOpenUnit() – open a scope device (p. 67)

```c
   PICO_STATUS ps2000aOpenUnit
   (
     int16_t    * handle,
     int8_t     * serial
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `* handle` | out | on exit, the result of the attempt to open a scope:<br>–1 : if the scope fails to open<br>0 : if no scope is found<br>> 0 : a number that uniquely identifies the scope<br>If a valid handle is returned, it must be used in all subsequent calls to API functions to identify this scope. |
| `* serial` | in | on entry, a null-terminated string containing the serial number of the scope to be opened. If serial is NULL then the function opens the first scope found; otherwise, it tries to open the scope that matches the string. |

**Returns**

- `PICO_OK`
- `PICO_OS_NOT_SUPPORTED`
- `PICO_OPEN_OPERATION_IN_PROGRESS`
- `PICO_EEPROM_CORRUPT`
- `PICO_KERNEL_DRIVER_TOO_OLD`
- `PICO_FPGA_FAIL`
- `PICO_MEMORY_CLOCK_FREQUENCY`
- `PICO_FW_FAIL`
- `PICO_MAX_UNITS_OPENED`
- `PICO_NOT_FOUND` (if the specified unit was not found)
- `PICO_NOT_RESPONDING`
- `PICO_MEMORY_FAIL`
- `PICO_ANALOG_BOARD`
- `PICO_CONFIG_FAIL_AWG`
- `PICO_INITIALISE_FPGA`

**Notes**

- Applicability: All modes.
- This function opens a PicoScope 2000 Series (A API) scope attached to the computer. The maximum number of units that can be opened depends on the operating system, the kernel driver and the computer.
- ⚠ manual note: `handle` is documented as `–1` / `0` / `> 0` and the function also returns a `PICO_STATUS`. The manual does not say how the two interact (for example whether `PICO_NOT_FOUND` goes together with handle `0` or `–1`). `PICO_NOT_FOUND` is annotated "(if the specified unit was not found)".
- ⚠ manual note: the manual does not state whether the `serial` comparison is case-sensitive, and does not state which string (see §3.4 ⚠ note) it must equal.
- ⚠ manual note: §2.9 (p. 29) writes `handle1 = ps2000aOpenUnit()` as pseudo-code; that is not this signature.

picosdk: ps2000a.ps2000aOpenUnit, argtypes = [c_void_p, c_char_p], restype = c_uint32 (the same ctypes function object is also set as ps2000a._OpenUnit)
⚠ picosdk mismatch: the wrapper's `doc` string names the first argument `int16_t *status` (manual: `* handle`). Argument count, order and ctypes types agree; this is a name difference only.

### §3.33 ps2000aOpenUnitAsync() – open a scope device without blocking (p. 68)

```c
   PICO_STATUS ps2000aOpenUnitAsync
   (
     int16_t    * status
     int8_t     * serial
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `* status` | out | a status code:<br>0 if the open operation was disallowed because another open operation is in progress<br>1 if the open operation was successfully started |
| `* serial` | in | see ps2000aOpenUnit(). |

**Returns**

- `PICO_OK`
- `PICO_OPEN_OPERATION_IN_PROGRESS`
- `PICO_OPERATION_FAILED`

**Notes**

- Applicability: All modes.
- This function opens a scope without blocking the calling thread. You can find out when it has finished by periodically calling ps2000aOpenUnitProgress() until that function returns a non-zero value.
- ⚠ manual note: "until that function returns a non-zero value" is ambiguous: ps2000aOpenUnitProgress() (§3.34) returns a `PICO_STATUS`, and `PICO_OK` is the code the manual lists first. The manual's argument text says `complete` is "set to 1 when the open operation has finished", and `progressPercent` "100% implies that the open operation is complete".
- ⚠ manual note: the prototype has no comma after `* status`.

picosdk: ps2000a.ps2000aOpenUnitAsync, argtypes = [c_void_p, c_char_p], restype = c_uint32 (the same ctypes function object is also set as ps2000a._OpenUnitAsync)

### §3.34 ps2000aOpenUnitProgress() – check progress of OpenUnit call (p. 69)

```c
   PICO_STATUS ps2000aOpenUnitProgress
   (
     int16_t    * handle,
     int16_t    * progressPercent,
     int16_t    * complete
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `* handle` | out | see ps2000aOpenUnit(). This handle is valid only if the function returns PICO_OK. |
| `* progressPercent` | out | on exit, the percentage progress towards opening the scope. 100% implies that the open operation is complete. |
| `* complete` | out | set to 1 when the open operation has finished. |

**Returns**

- `PICO_OK`
- `PICO_NULL_PARAMETER`
- `PICO_OPERATION_FAILED`

**Notes**

- Applicability: Use after ps2000aOpenUnitAsync().
- This function checks on the progress of a request made to ps2000aOpenUnitAsync() to open a scope.

picosdk: ps2000a.ps2000aOpenUnitProgress, argtypes = [c_void_p, c_void_p, c_void_p], restype = c_uint32 (the same ctypes function object is also set as ps2000a._OpenUnitProgress)

### §3.2 ps2000aCloseUnit() – close a scope device (p. 31)

```c
   PICO_STATUS ps2000aCloseUnit
   (
     int16_t  handle
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |

**Returns**

- `PICO_OK`
- `PICO_HANDLE_INVALID`
- `PICO_USER_CALLBACK`
- `PICO_DRIVER_FUNCTION`

**Notes**

- Applicability: All modes.
- This function shuts down an oscilloscope.
- ⚠ manual note: the manual lists `PICO_HANDLE_INVALID` here (and under ps2000aFlashLed §3.5 and ps2000aGetChannelInformation §3.7), while all other sections that list an invalid-handle code (for example §3.35, §3.17, §3.6) spell it `PICO_INVALID_HANDLE`. Both spellings occur; the manual does not say they are the same code.
- ⚠ manual note: the manual does not say whether ps2000aCloseUnit() stops a capture that is still running, nor whether ps2000aStop() must precede it; the numbered procedures (§2.2 steps 7 and 8; §2.6.1.1 steps 11 and 13) show ps2000aStop() before ps2000aCloseUnit().

picosdk: ps2000a.ps2000aCloseUnit, argtypes = [c_int16], restype = c_uint32 (the same ctypes function object is also set as ps2000a._CloseUnit)

### §3.17 ps2000aGetUnitInfo() – get information about scope device (p. 47)

```c
   PICO_STATUS ps2000aGetUnitInfo
   (
     int16_t       handle,
     int8_t      * string,
     int16_t       stringLength,
     int16_t     * requiredSize
     PICO_INFO     info
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). If an invalid handle is passed, only the driver versions can be read. |
| `* string` | out | on exit, the unit information string selected specified by the info argument. If string is NULL, only requiredSize is returned. |
| `stringLength` | in | the maximum number of chars that may be written to string. |
| `* requiredSize` | out | on exit, the required length of the string array. |
| `info` | in | a number specifying what information is required. The possible values are listed in the table below. |

`info` values (table from p. 47; "Example" is the manual's example string):

| info | Name | Meaning (manual) | Example |
|---|---|---|---|
| 0 | PICO_DRIVER_VERSION | Version number of PicoScope 2000A DLL | 1.0.0.1 |
| 1 | PICO_USB_VERSION | Type of USB connection to device: 1.1 or 2.0 | 2.0 |
| 2 | PICO_HARDWARE_VERSION | Hardware version of device | 1 |
| 3 | PICO_VARIANT_INFO | Variant number of device | 2206 |
| 4 | PICO_BATCH_AND_SERIAL | Batch and serial number of device | KJL87/006 |
| 5 | PICO_CAL_DATE | Calibration date of device | 30Sep09 |
| 6 | PICO_KERNEL_VERSION | Version of kernel driver | 1.0 |
| 7 | PICO_DIGITAL_HARDWARE_VERSION | Hardware version of the digital section | 1 |
| 8 | PICO_ANALOGUE_HARDWARE_VERSION | Hardware version of the analog section | 1 |
| 9 | PICO_FIRMWARE_VERSION_1 |  | 1.0.0.0 |
| 10 | PICO_FIRMWARE_VERSION_2 |  | 1.0.0.0 |

**Returns**

- `PICO_OK`
- `PICO_INVALID_HANDLE`
- `PICO_NULL_PARAMETER`
- `PICO_INVALID_INFO`
- `PICO_INFO_UNAVAILABLE`
- `PICO_DRIVER_FUNCTION`

**Notes**

- Applicability: All modes.
- This function retrieves information about the specified oscilloscope. If the device fails to open, or no device is opened only the driver version is available.
- ⚠ manual note: the prototype has no comma after `* requiredSize`.
- ⚠ manual note: "the unit information string selected specified by the info argument" is the manual's wording (sic).
- ⚠ manual note: the table lists info codes 0 to 10 only; rows 9 and 10 have no description text.
- ⚠ manual note: the manual does not give the string returned by `PICO_VARIANT_INFO` for a 2207B MSO (the only example is "2206"), nor its exact format.

picosdk: ps2000a.ps2000aGetUnitInfo, argtypes = [c_int16, c_char_p, c_int16, c_void_p, c_uint32], restype = c_uint32 (the same ctypes function object is also set as ps2000a._GetUnitInfo)
⚠ picosdk mismatch: `picosdk.constants.PICO_INFO` (attribute `ps2000a.PICO_INFO`) has codes 0x00 to 0x0A with the same names as the manual's table, and three further names that the manual does not list: `PICO_MAC_ADDRESS` (0x0B), `PICO_SHADOW_CAL` (0x0C), `PICO_IPP_VERSION` (0x0D).

### §3.35 ps2000aPingUnit() – check communication with opened device (p. 70)

```c
   PICO_STATUS ps2000aPingUnit
   (
     int16_t    handle
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |

**Returns**

- `PICO_OK`
- `PICO_INVALID_HANDLE`
- `PICO_DRIVER_FUNCTION`
- `PICO_BUSY`
- `PICO_NOT_RESPONDING`

**Notes**

- Applicability: All modes.
- This function can be used to check that the already opened device is still connected to the USB port and communication is successful.

picosdk: ps2000a.ps2000aPingUnit, argtypes = [c_int16], restype = c_uint32 (the same ctypes function object is also set as ps2000a._PingUnit)

### §3.5 ps2000aFlashLed() – flash the front-panel LED (p. 34)

```c
   PICO_STATUS ps2000aFlashLed
   (
     int16_t handle,
     int16_t start
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `start` | in | the action required:<br><0 : flash the LED indefinitely<br>0 : stop the LED flashing<br>>0 : flash the LED start times. If the LED is already flashing on entry to this function, the flash count will be reset to start. |

**Returns**

- `PICO_OK`
- `PICO_HANDLE_INVALID`
- `PICO_BUSY`
- `PICO_DRIVER_FUNCTION`
- `PICO_NOT_RESPONDING`

**Notes**

- Applicability: All modes.
- This function flashes the LED on the front of the scope without blocking the calling thread. Calls to ps2000aRunStreaming() and ps2000aRunBlock() cancel any flashing started by this function. It is not possible to set the LED to be constantly illuminated, as this state is used to indicate that the scope has not been initialized.

picosdk: ps2000a.ps2000aFlashLed, argtypes = [c_int16, c_int16], restype = c_uint32 (the same ctypes function object is also set as ps2000a._FlashLed)

### §3.7 ps2000aGetChannelInformation() – get list of available ranges (p. 36)

```c
   PICO_STATUS ps2000aGetChannelInformation
   (
     int16_t                  handle,
     PS2000A_CHANNEL_INFO     info
     int32_t                  probe
     int32_t                * ranges
     int32_t                * length
     int32_t                  channels
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `info` | in | the type of information required. The following value is currently supported:<br>PS2000A_CI_RANGES |
| `probe` | in | not used, must be set to 0. |
| `* ranges` | out | an array that will be populated with available PS2000A_RANGE values for the given info. If NULL, length is set to the number of ranges available. |
| `* length` | in/out | input: length of ranges array; output: number of elements written to ranges array. |
| `channels` | in | the channel for which the information is required. |

**Returns**

- `PICO_OK`
- `PICO_HANDLE_INVALID`
- `PICO_BUSY`
- `PICO_DRIVER_FUNCTION`
- `PICO_NOT_RESPONDING`
- `PICO_NULL_PARAMETER`
- `PICO_INVALID_CHANNEL`
- `PICO_INVALID_INFO`

**Notes**

- Applicability: All modes.
- This function queries which ranges are available on a scope device.
- ⚠ manual note: the prototype has no commas after `info`, `probe`, `* ranges` and `* length`.
- ⚠ manual note: `channels` is typed `int32_t` and described as "the channel for which the information is required"; the manual does not say which enum or values to pass (`PS2000A_CHANNEL_A` etc. are described under ps2000aSetChannel()), and does not give the numeric value of `PS2000A_CI_RANGES`.
- ⚠ manual note: the manual does not say whether `ranges` entries are the `PS2000A_RANGE` enum values or something else beyond "available PS2000A_RANGE values"; no numeric values for `PS2000A_RANGE` are given anywhere in the manual.

picosdk: ps2000a.ps2000aGetChannelInformation, argtypes = [c_int16, c_int32, c_int32, c_int32, c_int32, c_int32], restype = c_uint32 (the same ctypes function object is also set as ps2000a._GetChannelInformation)
⚠ picosdk mismatch: the wrapper declares `ranges` and `length` as `c_int32` (the manual prototype has `int32_t * ranges` and `int32_t * length`, i.e. pointers). Argument count and order agree (6); the types of arguments 4 and 5 differ. Also, the wrapper defines no `PS2000A_CHANNEL_INFO` enum / `PS2000A_CI_RANGES` constant (its `doc` string mentions `PS2000A_CHANNEL_INFO info` but no attribute holds the type).

### §3.6 ps2000aGetAnalogueOffset() – get allowable offset range (p. 35)

```c
   PICO_STATUS ps2000aGetAnalogueOffset
   (
     int16_t              handle,
     PS2000A_RANGE        range,
     PS2000A_COUPLING     coupling
     float              * maximumVoltage,
     float              * minimumVoltage
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `range` | in | the voltage range to be used when gathering the min and max information. |
| `coupling` | in | the type of AC/DC coupling used. |
| `* maximumVoltage` | out | output: maximum voltage allowed for the range. Pointer will be ignored if NULL. If device does not support analog offset, zero will be returned. |
| `* minimumVoltage` | out | output: minimum voltage allowed for the range. Pointer will be ignored if NULL. If device does not support analog offset, zero will be returned. |

If both maximumVoltage and minimumVoltage are NULL, the driver will return PICO_NULL_PARAMETER.

**Returns**

- `PICO_OK`
- `PICO_INVALID_HANDLE`
- `PICO_DRIVER_FUNCTION`
- `PICO_INVALID_VOLTAGE_RANGE`
- `PICO_NULL_PARAMETER`

**Notes**

- Applicability: All ps2000a units except the PicoScope 2205 MSO.
- This function is used to get the maximum and minimum allowable analog offset for a specific voltage range.
- ⚠ manual note: the prototype has no comma after `coupling`.
- ⚠ manual note: the Returns list here uses `PICO_INVALID_HANDLE`; §3.2 uses `PICO_HANDLE_INVALID`.
- ⚠ manual note: the unit of the returned offsets is not stated ("maximum voltage allowed for the range"; typed `float`). `range` and `coupling` take `PS2000A_RANGE` and `PS2000A_COUPLING` values (see §3.39).

picosdk: ps2000a.ps2000aGetAnalogueOffset, argtypes = [c_int16, c_int32, c_int32, c_void_p, c_void_p], restype = c_uint32 (the same ctypes function object is also set as ps2000a._GetAnalogueOffset)


## Channel setup, timebase, trigger

### §3.39 ps2000aSetChannel() – set up input channel (p. 76)

```c
   PICO_STATUS ps2000aSetChannel
   (
     int16_t             handle,
     PS2000A_CHANNEL     channel,
     int16_t             enabled,
     PS2000A_COUPLING    type,
     PS2000A_RANGE       range,
     float               analogOffset
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `channel` | in | the channel to be configured. The values are:<br>PS2000A_CHANNEL_A: Channel A input<br>PS2000A_CHANNEL_B: Channel B input<br>PS2000A_CHANNEL_C: Channel C input<br>PS2000A_CHANNEL_D: Channel D input |
| `enabled` | in | TRUE to enable the channel, FALSE to disable it. |
| `type` | in | the impedance and coupling type. The values are:<br>PS2000A_AC: 1 megohm impedance, AC coupling. The channel accepts input frequencies from about 1 hertz up to its maximum analog bandwidth.<br>PS2000A_DC: 1 megohm impedance, DC coupling. The channel accepts all input frequencies from zero (DC) up to its maximum analog bandwidth. |
| `range` | in | the input voltage range: |
| `analogOffset` | in | a voltage to add to the input channel before digitization. The allowable range of offsets can be obtained from ps2000aGetAnalogueOffset() and depends on the input range selected for the channel. This argument is ignored if the device is a PicoScope 2205 MSO. |

`range` values (verbatim from the manual, three columns in the PDF):

| Constant | Range | Constant | Range | Constant | Range |
|---|---|---|---|---|---|
| PS2000A_20MV: | ±20 mV | PS2000A_500MV: | ±500 mV | PS2000A_5V: | ±5 V |
| PS2000A_50MV: | ±50 mV | PS2000A_1V: | ±1 V | PS2000A_10V: | ±10 V |
| PS2000A_100MV: | ±100 mV | PS2000A_2V: | ±2 V | PS2000A_20V: | ±20 V |
| PS2000A_200MV: | ±200 mV |  |  |  |  |

**Returns**

- `PICO_OK`
- `PICO_USER_CALLBACK`
- `PICO_INVALID_HANDLE`
- `PICO_INVALID_CHANNEL`
- `PICO_INVALID_VOLTAGE_RANGE`
- `PICO_INVALID_COUPLING`
- `PICO_INVALID_ANALOGUE_OFFSET`
- `PICO_DRIVER_FUNCTION`

**Notes**

- Applicability: All modes.
- This function specifies whether an input channel is to be enabled, its input coupling type, voltage range, analog offset.
- Analogue offset, everything the manual says: (1) ps2000aSetChannel() `analogOffset`: "a voltage to add to the input channel before digitization. The allowable range of offsets can be obtained from ps2000aGetAnalogueOffset() and depends on the input range selected for the channel. This argument is ignored if the device is a PicoScope 2205 MSO." (2) ps2000aGetAnalogueOffset() (§3.6) applicability: "All ps2000a units except the PicoScope 2205 MSO"; "If device does not support analog offset, zero will be returned." (3) `PICO_INVALID_ANALOGUE_OFFSET` is listed under Returns above.
- The result of ps2000aGetTimebase() "depends on the number of channels enabled by the last call to ps2000aSetChannel()" (§3.13).
- ⚠ manual note: the manual does not give numeric values for `PS2000A_CHANNEL`, `PS2000A_COUPLING` or `PS2000A_RANGE` (see §4.2). The `range` list contains only `PS2000A_20MV` to `PS2000A_20V` (10 constants); no `PS2000A_10MV` or `PS2000A_50V`.
- ⚠ manual note: `PS2000A_CHANNEL_C` and `PS2000A_CHANNEL_D` are listed for all devices; the manual does not say what is returned when a 2-channel device is asked to configure them (`PICO_INVALID_CHANNEL` is in the Returns list but the text does not tie it to this case).
- ⚠ manual note: the units/semantics of `enabled` are only "TRUE ... FALSE"; the numeric values of TRUE and FALSE are not defined in the manual.

picosdk: ps2000a.ps2000aSetChannel, argtypes = [c_int16, c_int32, c_int16, c_int32, c_int32, c_float], restype = c_uint32 (the same ctypes function object is also set as ps2000a._SetChannel)
picosdk enums (cross-check only; values are NOT in the manual): `ps2000a.PS2000A_CHANNEL` = {PS2000A_CHANNEL_A: 0, PS2000A_CHANNEL_B: 1, PS2000A_CHANNEL_C: 2, PS2000A_CHANNEL_D: 3, PS2000A_EXTERNAL: 4, PS2000A_MAX_CHANNELS: 4, PS2000A_TRIGGER_AUX: 5, PS2000A_MAX_TRIGGER_SOURCE: 6}; `ps2000a.PS2000A_COUPLING` = {PS2000A_AC: 0, PS2000A_DC: 1}; `ps2000a.PS2000A_RANGE` = {PS2000A_10MV: 0, PS2000A_20MV: 1, PS2000A_50MV: 2, PS2000A_100MV: 3, PS2000A_200MV: 4, PS2000A_500MV: 5, PS2000A_1V: 6, PS2000A_2V: 7, PS2000A_5V: 8, PS2000A_10V: 9, PS2000A_20V: 10, PS2000A_50V: 11, PS2000A_MAX_RANGES: 12}.
⚠ picosdk mismatch: `ps2000a.PS2000A_RANGE` contains `PS2000A_10MV` and `PS2000A_50V`, which the manual's `range` list (§3.39) does not contain; the manual's 10 names are present with the same spelling. `ps2000a.PS2000A_CHANNEL` additionally contains `PS2000A_EXTERNAL`, `PS2000A_MAX_CHANNELS`, `PS2000A_TRIGGER_AUX`, `PS2000A_MAX_TRIGGER_SOURCE`, which §3.39 does not list. Channel and coupling names match the manual.

### §3.13 ps2000aGetTimebase() – find out what timebases are available (p. 42)

```c
   PICO_STATUS ps2000aGetTimebase
   (
     int16_t       handle,
     uint32_t      timebase,
     int32_t       noSamples,
     int32_t     * timeIntervalNanoseconds,
     int16_t       oversample,
     int32_t     * maxSamples
     uint32_t      segmentIndex
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `timebase` | in | see timebase guide |
| `noSamples` | in | the number of samples required |
| `* timeIntervalNanoseconds` | out | on exit, the time interval between readings at the selected timebase. Use NULL if not required. In ETS mode this argument is not valid; use the sample time returned by ps2000aSetEts() instead. |
| `oversample` | in | not used |
| `* maxSamples` | out | on exit, the maximum number of samples available. The scope allocates a certain amount of memory for internal overheads and this may vary depending on the number of segments, number of channels enabled, and the timebase chosen. Use NULL if not required. |
| `segmentIndex` | in | the index of the memory segment to use. |

**Returns**

- `PICO_OK`
- `PICO_INVALID_HANDLE`
- `PICO_TOO_MANY_SAMPLES`
- `PICO_INVALID_CHANNEL`
- `PICO_INVALID_TIMEBASE`
- `PICO_INVALID_PARAMETER`
- `PICO_SEGMENT_OUT_OF_RANGE`
- `PICO_DRIVER_FUNCTION`

**Notes**

- Applicability: All modes.
- This function calculates the sampling rate and maximum number of samples for a given timebase under the specified conditions. The result depends on the number of channels enabled by the last call to ps2000aSetChannel().
- This function is provided for use with programming languages that do not support the float data type. The value returned in the timeIntervalNanoseconds argument is restricted to integers. If your programming language supports the float type, we recommend that you use ps2000aGetTimebase2() instead.
- To use ps2000aGetTimebase() or ps2000aGetTimebase2(), first estimate the timebase number that you require using the information in the timebase guide. Next, call one of these functions with the timebase that you have just chosen and verify that the value returned in timeIntervalNanoseconds is the one you require. You may need to iterate this process until you obtain the time interval that you need.
- "timebase guide" refers to §2.7 Timebases (p. 28), transcribed above.
- ⚠ manual note: the prototype has no comma after `* maxSamples`.
- ⚠ manual note: the manual does not say what `timeIntervalNanoseconds` / `maxSamples` contain when a non-OK status is returned (for example `PICO_INVALID_TIMEBASE`).

picosdk: ps2000a.ps2000aGetTimebase, argtypes = [c_int16, c_uint32, c_int32, c_void_p, c_int16, c_void_p, c_uint32], restype = c_uint32 (the same ctypes function object is also set as ps2000a._GetTimebase)
⚠ picosdk mismatch: the wrapper's `doc` string names the sixth argument `totalSamples` (manual: `maxSamples`). Argument count (7), order and ctypes types agree with the manual; name difference only.

### §3.14 ps2000aGetTimebase2() – find out what timebases are available (p. 44)

```c
   PICO_STATUS ps2000aGetTimebase2
   (
     int16_t      handle,
     uint32_t     timebase,
     int32_t      noSamples,
     float      * timeIntervalNanoseconds,
     int16_t      oversample,
     int32_t    * maxSamples
     uint32_t     segmentIndex
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `* timeIntervalNanoseconds` | out | a pointer to the time interval between readings at the selected timebase. If a null pointer is passed, nothing will be written here. |
| all other arguments | see §3.13 | All other arguments: see ps2000aGetTimebase(). |

**Returns**

See ps2000aGetTimebase() (§3.13, status list above).

**Notes**

- Applicability: All modes.
- This function is an upgraded version of ps2000aGetTimebase(), and returns the time interval as a float rather than a long. This allows it to return sub-nanosecond time intervals. See ps2000aGetTimebase() for a full description.
- ⚠ manual note: the prototype has no comma after `* maxSamples`. The manual calls the GetTimebase output a "long" while its prototype types it `int32_t`.

picosdk: ps2000a.ps2000aGetTimebase2, argtypes = [c_int16, c_uint32, c_int32, c_void_p, c_int16, c_void_p, c_uint32], restype = c_uint32 (the same ctypes function object is also set as ps2000a._GetTimebase2)

### §3.56 ps2000aSetSimpleTrigger() – set up level triggers (p. 101)

```c
   PICO_STATUS ps2000aSetSimpleTrigger
   (
     int16_t                       handle,
     int16_t                       enable,
     PS2000A_CHANNEL               source,
     int16_t                       threshold,
     PS2000A_THRESHOLD_DIRECTION   direction,
     uint32_t                      delay,
     int16_t                       autoTrigger_ms
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `enable` | in | zero to disable the trigger; any non-zero value to set the trigger. |
| `source` | in | the channel on which to trigger. |
| `threshold` | in | the ADC count at which the trigger will fire. |
| `direction` | in | the direction in which the signal must move to cause a trigger. The following directions are supported: ABOVE, BELOW, RISING, FALLING and RISING_OR_FALLING. |
| `delay` | in | the time between the trigger occurring and the first sample being taken. For example, if delay=100, the scope would wait 100 sample periods before sampling. |
| `autoTrigger_ms` | in | the number of milliseconds the device will wait if no trigger occurs. If this is set to zero, the scope device will wait indefinitely for a trigger. |

**Returns**

- `PICO_OK`
- `PICO_INVALID_CHANNEL`
- `PICO_INVALID_PARAMETER`
- `PICO_MEMORY`
- `PICO_CONDITIONS`
- `PICO_INVALID_HANDLE`
- `PICO_USER_CALLBACK`
- `PICO_DRIVER_FUNCTION`

**Notes**

- Applicability: All modes.
- This function simplifies arming the trigger. It supports only the LEVEL trigger types on analog channels, and does not allow more than one channel to have a trigger applied to it. Any previous pulse width qualifier is canceled. The trigger threshold includes a small, fixed amount of hysteresis.
- autoTrigger semantics: the manual states only the `autoTrigger_ms` sentence above ("the number of milliseconds the device will wait if no trigger occurs. If this is set to zero, the scope device will wait indefinitely for a trigger."). Related text: ps2000aRunBlock() `timeIndisposedMs` "does not include any auto trigger timeout" (§3.37); ETS mode: "Auto trigger delay (autoTriggerMilliseconds) is ignored." (§2.6.3, p. 23).
- ⚠ manual note: the `direction` list is given without the `PS2000A_` prefix ("ABOVE, BELOW, RISING, FALLING and RISING_OR_FALLING"). The constants are defined in the `PS2000A_THRESHOLD_DIRECTION` table of §3.58 (p. 104), reproduced below. In that table `ABOVE` and `BELOW` have trigger type "gated" while this function says it "supports only the LEVEL trigger types"; the table has no type called "level" (its types are gated, threshold, window-qualified, window, none). The manual does not resolve this.
- ⚠ manual note: `autoTrigger_ms` is typed `int16_t`; the manual states no maximum value and no behaviour for negative values. `threshold` is typed `int16_t` ("the ADC count"); the manual gives no relation between this count and the selected range other than the ADC scaling in §2.3. `delay` is typed `uint32_t`; its maximum is not stated here (§3.60 says "Range: 0 to MAX_DELAY_COUNT", and the value of MAX_DELAY_COUNT is not given).
- ⚠ manual note: `source` is typed `PS2000A_CHANNEL`; the manual does not list the allowed values for this function beyond "the channel on which to trigger" ("on analog channels").

`PS2000A_THRESHOLD_DIRECTION` constants (this table is in §3.58 ps2000aSetTriggerChannelDirections(), p. 104; transcribed from the PDF page):

| Constant | Trigger type | Direction |
|---|---|---|
| PS2000A_ABOVE | gated | above the upper threshold |
| PS2000A_ABOVE_LOWER | gated | above the lower threshold |
| PS2000A_BELOW | gated | below the upper threshold |
| PS2000A_BELOW_LOWER | gated | below the lower threshold |
| PS2000A_RISING | threshold | rising edge, using upper threshold |
| PS2000A_RISING_LOWER | threshold | rising edge, using lower threshold |
| PS2000A_FALLING | threshold | falling edge, using upper threshold |
| PS2000A_FALLING_LOWER | threshold | falling edge, using lower threshold |
| PS2000A_RISING_OR_FALLING | threshold | either edge |
| PS2000A_INSIDE | window-qualified | inside window |
| PS2000A_OUTSIDE | window-qualified | outside window |
| PS2000A_ENTER | window | entering the window |
| PS2000A_EXIT | window | leaving the window |
| PS2000A_ENTER_OR_EXIT | window | entering or leaving the window |
| PS2000A_NONE | none | none |

⚠ manual note: the manual gives no numeric values for these constants. "upper threshold" / "lower threshold" are not defined for ps2000aSetSimpleTrigger(), which takes a single `threshold`.

picosdk: ps2000a.ps2000aSetSimpleTrigger, argtypes = [c_int16, c_int16, c_int32, c_int16, c_int32, c_uint32, c_int16], restype = c_uint32 (the same ctypes function object is also set as ps2000a._SetSimpleTrigger)
picosdk enum (cross-check only; values are NOT in the manual): `ps2000a.PS2000A_THRESHOLD_DIRECTION` = {PS2000A_ABOVE: 0, PS2000A_BELOW: 1, PS2000A_RISING: 2, PS2000A_FALLING: 3, PS2000A_RISING_OR_FALLING: 4, PS2000A_ABOVE_LOWER: 5, PS2000A_BELOW_LOWER: 6, PS2000A_RISING_LOWER: 7, PS2000A_FALLING_LOWER: 8, PS2000A_INSIDE: 0, PS2000A_OUTSIDE: 1, PS2000A_ENTER: 2, PS2000A_EXIT: 3, PS2000A_ENTER_OR_EXIT: 4, PS2000A_NONE: 2, PS2000A_POSITIVE_RUNT: 9, PS2000A_NEGATIVE_RUNT: 10}.
⚠ picosdk mismatch: all 15 constant names of the manual's table exist in `ps2000a.PS2000A_THRESHOLD_DIRECTION`, but six of them are aliases of other names in the wrapper (INSIDE = ABOVE, OUTSIDE = BELOW, ENTER = RISING, EXIT = FALLING, ENTER_OR_EXIT = RISING_OR_FALLING, NONE = RISING), whereas the manual lists them as separate constants with different trigger types. The wrapper also has `PS2000A_POSITIVE_RUNT` and `PS2000A_NEGATIVE_RUNT`, which the manual's table does not list.

### §3.60 ps2000aSetTriggerDelay() – set up post-trigger delay (p. 108)

```c
   PICO_STATUS ps2000aSetTriggerDelay
   (
     int16_t     handle,
     uint32_t    delay
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `delay` | in | the time between the trigger occurring and the first sample. For example, if delay=100 then the scope would wait 100 sample periods before sampling. At a timebase of 1 GS/s, or 1 ns per sample, the total delay would then be 100 x 1 ns = 100 ns. Range: 0 to MAX_DELAY_COUNT. |

**Returns**

- `PICO_OK`
- `PICO_INVALID_HANDLE`
- `PICO_USER_CALLBACK`
- `PICO_DRIVER_FUNCTION`

**Notes**

- Applicability: All modes (but delay is ignored in streaming mode).
- This function sets the post-trigger delay, which causes capture to start a defined time after the trigger event.
- ⚠ manual note: the numeric value of `MAX_DELAY_COUNT` is not given in the manual. ps2000aSetSimpleTrigger() (§3.56) also has a `delay` argument; the manual does not say how the two interact.

picosdk: ps2000a.ps2000aSetTriggerDelay, argtypes = [c_int16, c_uint32], restype = c_uint32 (the same ctypes function object is also set as ps2000a._SetTriggerDelay)


## Run, wait, buffers, retrieve, stop

### §3.37 ps2000aRunBlock() – capture in block mode (p. 72)

```c
   PICO_STATUS ps2000aRunBlock
   (
     int16_t              handle,
     int32_t              noOfPreTriggerSamples,
     int32_t              noOfPostTriggerSamples,
     uint32_t             timebase,
     int16_t              oversample,
     int32_t            * timeIndisposedMs,
     uint32_t             segmentIndex,
     ps2000aBlockReady    lpReady,
     void               * pParameter
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `noOfPreTriggerSamples` | in | the number of samples to store before the trigger event |
| `noOfPostTriggerSamples` | in | the number of samples to store after the trigger event<br>Note: the maximum number of samples returned is always noOfPreTriggerSamples + noOfPostTriggerSamples. This is true even if no trigger event has been set. |
| `timebase` | in | a number in the range 0 to 2^32 –1. See the guide to calculating timebase values. This argument is ignored in ETS mode, when ps2000aSetEts() selects the timebase instead. |
| `oversample` | in | not used |
| `* timeIndisposedMs` | out | on exit, the time, in milliseconds, that the scope will spend collecting samples. This does not include any auto trigger timeout. It is not valid in ETS capture mode. The pointer can be set to null if a value is not required. |
| `segmentIndex` | in | zero-based, which memory segment to use |
| `lpReady` | in | a pointer to the ps2000aBlockReady() callback function that the driver will call when the data has been collected. To use the ps2000aIsReady() polling method instead of a callback function, set this pointer to NULL. |
| `* pParameter` | in | a void pointer that is passed to the ps2000aBlockReady() callback function. The callback can use this pointer to return arbitrary data to the application. |

**Returns**

- `PICO_OK`
- `PICO_BUFFERS_NOT_SET` (in Overlapped mode)
- `PICO_INVALID_HANDLE`
- `PICO_USER_CALLBACK`
- `PICO_SEGMENT_OUT_OF_RANGE`
- `PICO_INVALID_CHANNEL`
- `PICO_INVALID_TRIGGER_CHANNEL`
- `PICO_INVALID_CONDITION_CHANNEL`
- `PICO_TOO_MANY_SAMPLES`
- `PICO_INVALID_TIMEBASE`
- `PICO_NOT_RESPONDING`
- `PICO_CONFIG_FAIL`
- `PICO_INVALID_PARAMETER`
- `PICO_NOT_RESPONDING`
- `PICO_TRIGGER_ERROR`
- `PICO_DRIVER_FUNCTION`
- `PICO_FW_FAIL`
- `PICO_NOT_ENOUGH_SEGMENTS` (in Bulk mode)
- `PICO_PULSE_WIDTH_QUALIFIER`
- `PICO_SEGMENT_OUT_OF_RANGE` (in Overlapped mode)
- `PICO_STARTINDEX_INVALID` (in Overlapped mode)
- `PICO_INVALID_SAMPLERATIO` (in Overlapped mode)
- `PICO_CONFIG_FAIL`

**Notes**

- Applicability: Block mode, rapid block mode.
- This function starts collecting data in block mode. For a step-by-step guide to this process, see Using block mode (§2.6.1.1, transcribed above).
- The number of samples is determined by noOfPreTriggerSamples and noOfPostTriggerSamples (see below for details). The total number of samples must not be more than the size of the segment referred to by segmentIndex.
- "the guide to calculating timebase values" refers to §2.7 Timebases.
- ⚠ transcription note: the text dump shows the `timebase` range as "0 to 23 2 –1"; the PDF page shows 2 with superscript 32, i.e. `2^32 –1`.
- ⚠ manual note: the Returns list repeats `PICO_NOT_RESPONDING` (twice), `PICO_CONFIG_FAIL` (twice) and has `PICO_SEGMENT_OUT_OF_RANGE` both plain and "(in Overlapped mode)". Items annotated "(in Overlapped mode)" / "(in Bulk mode)" are not block-mode single-shot codes.
- ⚠ manual note: the values of `status` passed to the callback are not listed (see §3.1).
- ⚠ manual note: `oversample` is "not used", but the manual's own rapid-block examples (§2.6.2.2 p. 19 and §2.6.2.3 p. 21, not transcribed here) pass the literal `1` for it: `ps2000aRunBlock(handle, 0, MAX_SAMPLES, 1, 1, &timeIndisposedMs, 0, lpReady, &pParameter);` (the two `1`s are the `timebase` and `oversample` arguments).
- ⚠ manual note: the manual does not say whether ps2000aGetTimebase() must be called before ps2000aRunBlock(); §2.6.1.1 step 3 uses it to select a timebase, and ps2000aRunBlock() takes the timebase number directly.
- ⚠ manual note: the manual does not say whether a trigger set with ps2000aSetSimpleTrigger() is applied by this call, or what happens when no trigger function was called ("PicoScope oscilloscopes can either start collecting data immediately or be programmed to wait for a trigger event", §2.5).

picosdk: ps2000a.ps2000aRunBlock, argtypes = [c_int16, c_int32, c_int32, c_uint32, c_int16, c_void_p, c_uint32, c_void_p, c_void_p], restype = c_uint32 (the same ctypes function object is also set as ps2000a._RunBlock)

### §3.1 ps2000aBlockReady() – find out if block-mode data ready (p. 30)

```c
    typedef void (CALLBACK *ps2000aBlockReady)
    (
      int16_t         handle,
      PICO_STATUS     status,
      void          * pParameter
    )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `status` | in | indicates whether an error occurred during collection of the data. |
| `* pParameter` | in/out | a void pointer passed from ps2000aRunBlock(). Your callback function can write to this location to send any data, such as a status flag, back to your application. |

**Returns**

nothing

**Notes**

- Applicability: Block mode only.
- This callback function is part of your application. You register it with the ps2000a driver using ps2000aRunBlock(), and the driver calls it back when block-mode data is ready. The callback function may check that data is available or detect that an error has occurred, but should not attempt to retrieve captured data by calling other ps2000a functions. After the callback function has returned, another part of your application can download the data using ps2000aGetValues().
- From §2.6 (p. 14): "Because the callback is called asynchronously from the rest of your application, in a separate thread, you must ensure that it does not corrupt any global variables while it runs."
- ⚠ manual note: this typedef uses `CALLBACK`; the other callback typedef in the manual (§3.3 ps2000aDataReady) uses `__stdcall`. The manual does not say what `status` values mean beyond "indicates whether an error occurred" (the code for success is not stated; `PICO_OK` is the manual's success code for function returns), and does not say what `status` is when ps2000aStop() aborts a pending run (ps2000aIsReady() §3.26 lists `PICO_CANCELLED` as a possible return).

picosdk: ps2000a.BlockReadyType = C_CALLBACK_FUNCTION_FACTORY(None, c_int16, c_uint32, c_void_p), i.e. restype None and argtypes (c_int16, c_uint32, c_void_p) for handle, status, pParameter. C_CALLBACK_FUNCTION_FACTORY is ctypes.WINFUNCTYPE on win32 and ctypes.CFUNCTYPE otherwise (picosdk/ctypes_wrapper.py). No mismatch with the manual's argument list.

### §3.26 ps2000aIsReady() – poll driver in block mode (p. 61)

```c
   PICO_STATUS ps2000aIsReady
   (
     int16_t     handle,
     int16_t   * ready
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `* ready` | out | output: indicates the state of the collection. If zero, the device is still collecting. If non-zero, the device has finished collecting and ps2000aGetValues() can be used to retrieve the data. |

**Returns**

- `PICO_OK`
- `PICO_INVALID_HANDLE`
- `PICO_DRIVER_FUNCTION`
- `PICO_NULL_PARAMETER`
- `PICO_NO_SAMPLES_AVAILABLE`
- `PICO_CANCELLED`
- `PICO_NOT_RESPONDING`

**Notes**

- Applicability: Block mode.
- This function may be used instead of a callback function to receive data from ps2000aRunBlock(). To use this method, pass a NULL pointer as the lpReady argument to ps2000aRunBlock(). You must then poll the driver to see if it has finished collecting the requested samples.
- ⚠ manual note: the manual gives no polling interval or timeout guidance.

picosdk: ps2000a.ps2000aIsReady, argtypes = [c_int16, c_void_p], restype = c_uint32 (the same ctypes function object is also set as ps2000a._IsReady)

### §3.40 ps2000aSetDataBuffer() – register data buffer with driver (p. 77)

```c
   PICO_STATUS ps2000aSetDataBuffer
   (
     int16_t                handle,
     int32_t                channel,
     int16_t              * buffer,
     int32_t                bufferLth,
     uint32_t               segmentIndex,
     PS2000A_RATIO_MODE     mode
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `channel` | in | the channel you want to use with the buffer. Use one of these values:<br>PS2000A_CHANNEL_A<br>PS2000A_CHANNEL_B<br>PS2000A_CHANNEL_C<br>PS2000A_CHANNEL_D<br>PS2000A_DIGITAL_PORT0 = 0x80 (MSO models only)<br>PS2000A_DIGITAL_PORT1 = 0x81 (MSO models only) |
| `* buffer` | out | pointer to the buffer. Each sample written to the buffer will be a 16-bit ADC count scaled according to the selected voltage range. |
| `bufferLth` | in | the size of the buffer array |
| `segmentIndex` | in | the number of the memory segment to be used |
| `mode` | in | the downsampling mode. See ps2000aGetValues() for the available modes, but note that a single call to ps2000aSetDataBuffer() can only associate one buffer with one downsampling mode. If you intend to call ps2000aGetValues() with more than one downsampling mode activated, then you must call ps2000aSetDataBuffer() several times to associate a separate buffer with each downsampling mode. |

**Returns**

- `PICO_OK`
- `PICO_INVALID_HANDLE`
- `PICO_INVALID_CHANNEL`
- `PICO_RATIO_MODE_NOT_SUPPORTED`
- `PICO_SEGMENT_OUT_OF_RANGE`
- `PICO_DRIVER_FUNCTION`
- `PICO_INVALID_PARAMETER`

**Notes**

- Applicability: Block, rapid block and streaming modes. All downsampling modes except aggregation.
- This function tells the driver where to store the data, either unprocessed or downsampled, that will be returned after the next call to one of the ps2000aGetValues...() functions. The function only allows you to specify a single buffer, so for aggregation mode, which requires two buffers, you need to call ps2000aSetDataBuffers() instead.
- You must allocate memory for the buffer before calling this function.
- ⚠ manual note: the direction of `* buffer` is not stated by the manual; "tells the driver where to store the data" implies the driver writes into it (shown as `out` here).
- ⚠ manual note: `bufferLth` is "the size of the buffer array"; the manual does not say whether this is a count of samples (int16_t elements) or bytes.
- ⚠ manual note: `channel` is typed `int32_t` here although ps2000aSetChannel() types it `PS2000A_CHANNEL`. The manual gives numeric values only for the digital ports.
- Call order: §2.6.1.1 step 7 (see the ⚠ note there about steps 5 to 7).

picosdk: ps2000a.ps2000aSetDataBuffer, argtypes = [c_int16, c_int32, c_void_p, c_int32, c_uint32, c_int32], restype = c_uint32 (the same ctypes function object is also set as ps2000a._SetDataBuffer)
⚠ picosdk mismatch: the wrapper's `doc` string names the second argument `channelOrPort` (manual: `channel`). Count (6), order and ctypes types agree; name difference only.

### §3.41 ps2000aSetDataBuffers() – register aggregated data buffers with driver (p. 78)

```c
   PICO_STATUS ps2000aSetDataBuffers
   (
     int16_t               handle,
     int32_t               channel,
     int16_t             * bufferMax,
     int16_t             * bufferMin,
     int32_t               bufferLth,
     uint32_t              segmentIndex,
     PS2000A_RATIO_MODE     mode
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `channel` | in | the channel for which you want to set the buffers. Use one of these constants:<br>PS2000A_CHANNEL_A<br>PS2000A_CHANNEL_B<br>PS2000A_CHANNEL_C<br>PS2000A_CHANNEL_D<br>PS2000A_DIGITAL_PORT0 = 0x80 (MSO models only)<br>PS2000A_DIGITAL_PORT1 = 0x81 (MSO models only) |
| `* bufferMax` | out | a user-allocated buffer to receive the maximum data values in aggregation mode, or the non-aggregated values otherwise. Each value is a 16-bit ADC count scaled according to the selected voltage range. |
| `* bufferMin` | out | a user-allocated buffer to receive the minimum data values in aggregation mode. Not normally used in other modes, but you can direct the driver to write non-aggregated values to this buffer by setting bufferMax to NULL. To enable aggregation, the downsampling ratio and mode must be set appropriately when calling one of the ps2000aGetValues...() functions. |
| `bufferLth` | in | the size of the bufferMax and bufferMin arrays. |
| `segmentIndex` | in | the number of the memory segment to be used. |
| `mode` | in | see ps2000aGetValues(). |

**Returns**

- `PICO_OK`
- `PICO_INVALID_HANDLE`
- `PICO_INVALID_CHANNEL`
- `PICO_RATIO_MODE_NOT_SUPPORTED`
- `PICO_SEGMENT_OUT_OF_RANGE`
- `PICO_DRIVER_FUNCTION`
- `PICO_INVALID_PARAMETER`

**Notes**

- Applicability: Block and streaming modes with aggregation.
- This function tells the driver the location of one or two buffers for receiving data. You need to allocate memory for the buffers before calling this function. If you do not need two buffers because you are not using aggregate mode, you can optionally use ps2000aSetDataBuffer() instead.

picosdk: ps2000a.ps2000aSetDataBuffers, argtypes = [c_int16, c_int32, c_void_p, c_void_p, c_int32, c_uint32, c_int32], restype = c_uint32 (the same ctypes function object is also set as ps2000a._SetDataBuffers)

### §3.18 ps2000aGetValues() – get block-mode data with callback (p. 49)

```c
   PICO_STATUS ps2000aGetValues
   (
     int16_t                handle,
     uint32_t               startIndex,
     uint32_t             * noOfSamples,
     uint32_t               downSampleRatio,
     PS2000A_RATIO_MODE     downSampleRatioMode,
     uint32_t               segmentIndex,
     int16_t              * overflow
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `startIndex` | in | a zero-based index that indicates the start point for data collection. It is measured in sample intervals from the start of the buffer. |
| `* noOfSamples` | in/out | on entry, the number of samples required. On exit, the actual number retrieved. The number of samples retrieved will not be more than the number requested, and the data retrieved starts at startIndex. |
| `downSampleRatio` | in | the downsampling factor that will be applied to the raw data. |
| `downSampleRatioMode` | in | which downsampling mode to use. The available values are:<br>PS2000A_RATIO_MODE_NONE (downSampleRatio is ignored)<br>PS2000A_RATIO_MODE_AGGREGATE<br>PS2000A_RATIO_MODE_AVERAGE<br>PS2000A_RATIO_MODE_DECIMATE<br>AGGREGATE, AVERAGE, DECIMATE are single-bit constants that can be ORed to apply multiple downsampling modes to the same data. |
| `segmentIndex` | in | the zero-based number of the memory segment where the data is stored. |
| `* overflow` | out | on exit, a set of flags that indicate whether an overvoltage has occurred on any of the channels. It is a bit field with bit 0 denoting Channel A. |

**Returns**

- `PICO_OK`
- `PICO_INVALID_HANDLE`
- `PICO_NO_SAMPLES_AVAILABLE`
- `PICO_DEVICE_SAMPLING`
- `PICO_NULL_PARAMETER`
- `PICO_SEGMENT_OUT_OF_RANGE`
- `PICO_STARTINDEX_INVALID`
- `PICO_ETS_NOT_RUNNING`
- `PICO_BUFFERS_NOT_SET`
- `PICO_INVALID_PARAMETER`
- `PICO_TOO_MANY_SAMPLES`
- `PICO_DATA_NOT_AVAILABLE`
- `PICO_STARTINDEX_INVALID`
- `PICO_INVALID_SAMPLERATIO`
- `PICO_INVALID_CALL`
- `PICO_NOT_RESPONDING`
- `PICO_MEMORY`
- `PICO_RATIO_MODE_NOT_SUPPORTED`
- `PICO_DRIVER_FUNCTION`

**Notes**

- Applicability: Block mode, rapid block mode.
- This function retrieves block-mode data, either with or without downsampling, starting at the specified sample number. It is used to get the stored data from the scope after data collection has stopped, and store it in a user buffer previously passed to ps2000aSetDataBuffer() or ps2000aSetDataBuffers(). It blocks the calling function while retrieving data.
- If multiple channels are enabled, a single call to this function is sufficient to retrieve data for all channels.
- Note that if you are using block mode and call this function before the oscilloscope is ready, no capture will be available and the driver will return PICO_NO_SAMPLES_AVAILABLE.
- Overflow bit field, everything the manual says: ps2000aGetValues() `overflow`: "a set of flags that indicate whether an overvoltage has occurred on any of the channels. It is a bit field with bit 0 denoting Channel A."; ps2000aDataReady() (§3.3) `overflow`: "a set of flags that indicates whether an overvoltage has occurred and on which channels. It is a bit field with bit 0 representing Channel A."
- ⚠ manual note: the section title says "with callback", but the description says "It blocks the calling function while retrieving data" and the prototype has no callback argument. (The callback variant is ps2000aGetValuesAsync(), §3.19, not transcribed.)
- ⚠ manual note: the Returns list names `PICO_STARTINDEX_INVALID` twice; it also lists `PICO_ETS_NOT_RUNNING`, `PICO_RATIO_MODE_NOT_SUPPORTED`, `PICO_MEMORY` and `PICO_DEVICE_SAMPLING` without explanation.
- ⚠ manual note: the manual states only that bit 0 is Channel A. It does not state in words that bit 1 is Channel B, bit 2 Channel C, bit 3 Channel D, nor which bits (if any) apply to digital ports, nor whether the bits for disabled channels are zero.
- ⚠ manual note: the manual does not say what the data buffers contain, or what is returned, for a channel that is disabled or has no buffer registered (`PICO_BUFFERS_NOT_SET` is in the Returns list but is not explained).
- Buffers must be registered with ps2000aSetDataBuffer()/ps2000aSetDataBuffers() before this call, per the first Notes paragraph and §2.6.1.1 step 7.

#### §3.18.1 Downsampling modes (p. 50)

Various methods of data reduction, or downsampling, are possible with the PicoScope 2000 Series oscilloscopes. The downsampling is done at high speed, making your application faster and more responsive than if you had to do all your own data processing.

You specify the downsampling mode when you call one of the data collection functions such as ps2000aGetValues(). The following modes are available:

| Constant | Meaning (manual) |
|---|---|
| PS2000A_RATIO_MODE_NONE | No downsampling. Returns the raw data values. |
| PS2000A_RATIO_MODE_AGGREGATE | Reduces every block of n values to just two values: a minimum and a maximum. The minimum and maximum values are returned in two separate buffers. |
| PS2000A_RATIO_MODE_AVERAGE | Reduces every block of n values to a single value representing the average (arithmetic mean) of all the values. Equivalent to the 'oversampling' function on older scopes. |
| PS2000A_RATIO_MODE_DECIMATE | Reduces every block of n values to just the first value in the block, discarding all the other values. |

**Retrieving multiple types of downsampled data**

You can optionally retrieve data using more than one downsampling mode with a single call to ps2000aGetValues(). Set up a buffer for each downsampling mode by calling ps2000aSetDataBuffer(). Then, when calling ps2000aGetValues(), set downSampleRatioMode to the bitwise OR of the required downsampling modes.

**Retrieving both raw and downsampled data**

You cannot retrieve raw data and downsampled data in a single operation. If you require both raw and downsampled data, first retrieve the downsampled data as described above and then continue as follows:

1. Call ps2000aStop().
2. Set up a data buffer for each channel using ps2000aSetDataBuffer() with the ratio mode set to PS2000A_RATIO_MODE_NONE.
3. Call ps2000aGetValues() to retrieve the data.

(Steps 2 and 3 are on p. 51.)

⚠ manual note: the manual gives no numeric values for the `PS2000A_RATIO_MODE_*` constants; only that AGGREGATE, AVERAGE and DECIMATE are "single-bit constants". With `PS2000A_RATIO_MODE_NONE` the manual says `downSampleRatio` is ignored; it does not say what value to pass (a ratio of 1 is used in the manual's rapid-block example, p. 20, and a ratio of 10 in the aggregation example, p. 22).

picosdk: ps2000a.ps2000aGetValues, argtypes = [c_int16, c_uint32, c_void_p, c_uint32, c_int32, c_uint32, c_void_p], restype = c_uint32 (the same ctypes function object is also set as ps2000a._GetValues)
picosdk enum (cross-check only; values are NOT in the manual): `ps2000a.PS2000A_RATIO_MODE` = {PS2000A_RATIO_MODE_NONE: 0, PS2000A_RATIO_MODE_AGGREGATE: 1, PS2000A_RATIO_MODE_DECIMATE: 2, PS2000A_RATIO_MODE_AVERAGE: 4}. Names match the manual's four constants; AGGREGATE (1), DECIMATE (2), AVERAGE (4) are single bits, consistent with the manual's "single-bit constants" statement. No mismatch.

### §3.28 ps2000aMaximumValue() – get maximum ADC count in GetValues calls (p. 63)

```c
   PICO_STATUS ps2000aMaximumValue
   (
     int16_t     handle
     int16_t   * value
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `* value` | out | output: the maximum ADC value. |

**Returns**

- `PICO_OK`
- `PICO_USER_CALLBACK`
- `PICO_INVALID_HANDLE`
- `PICO_TOO_MANY_SEGMENTS`
- `PICO_MEMORY`
- `PICO_DRIVER_FUNCTION`

**Notes**

- Applicability: All modes.
- This function returns the maximum ADC count returned by calls to the GetValues functions.
- §2.3 (p. 11) tabulates the value as 32 512 (hex 7F00) for ps2000aMaximumValue().
- ⚠ manual note: the prototype has no comma after `handle`. The Returns list contains `PICO_TOO_MANY_SEGMENTS` and `PICO_MEMORY`, which are not explained for this function (they are identical to the list of ps2000aMemorySegments(), §3.29).

picosdk: ps2000a.ps2000aMaximumValue, argtypes = [c_int16, c_void_p], restype = c_uint32 (the same ctypes function object is also set as ps2000a._MaximumValue)

### §3.30 ps2000aMinimumValue() – get minimum ADC count in GetValues calls (p. 65)

```c
   PICO_STATUS ps2000aMinimumValue
   (
     int16_t      handle
     int16_t    * value
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `* value` | out | output: the minimum ADC value. |

**Returns**

- `PICO_OK`
- `PICO_USER_CALLBACK`
- `PICO_INVALID_HANDLE`
- `PICO_TOO_MANY_SEGMENTS`
- `PICO_MEMORY`
- `PICO_DRIVER_FUNCTION`

**Notes**

- Applicability: All modes.
- This function returns the minimum ADC count returned by calls to the GetValues functions.
- §2.3 (p. 11) tabulates the value as –32 512 (hex 8100) for ps2000aMinimumValue().
- ⚠ manual note: the prototype has no comma after `handle`. The Returns list contains `PICO_TOO_MANY_SEGMENTS` and `PICO_MEMORY`, which are not explained for this function.

picosdk: ps2000a.ps2000aMinimumValue, argtypes = [c_int16, c_void_p], restype = c_uint32 (the same ctypes function object is also set as ps2000a._MinimumValue)

### §3.16 ps2000aGetTriggerTimeOffset64() – find out when trigger occurred (64-bit) (p. 46)

```c
   PICO_STATUS ps2000aGetTriggerTimeOffset64
   (
     int16_t                 handle,
     int64_t               * time,
     PS2000A_TIME_UNITS    * timeUnits,
     uint32_t                segmentIndex
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `* time` | out | on exit, the time at which the trigger point occurred. |
| `* timeUnits` | out | on exit, the time units in which time is measured. The possible values are:<br>PS2000A_FS<br>PS2000A_PS<br>PS2000A_NS<br>PS2000A_US<br>PS2000A_MS<br>PS2000A_S |
| `segmentIndex` | in | the number of the memory segment for which the information is required. |

**Returns**

- `PICO_OK`
- `PICO_INVALID_HANDLE`
- `PICO_DEVICE_SAMPLING`
- `PICO_SEGMENT_OUT_OF_RANGE`
- `PICO_NOT_USED_IN_THIS_CAPTURE_MODE`
- `PICO_NOT_RESPONDING`
- `PICO_NULL_PARAMETER`
- `PICO_NO_SAMPLES_AVAILABLE`
- `PICO_DRIVER_FUNCTION`

**Notes**

- Applicability: Block mode, rapid block mode.
- This function retrieves the time offset for a waveform obtained in block mode or rapid block mode. The time offset of a waveform is the delay from the trigger sampling instant to the time at which the driver estimates the waveform to have crossed the trigger threshold. You can add this offset to the time of each sample in the waveform to reduce trigger jitter. Without using the time offset, trigger jitter can be up to 1 sample period; adding the time offset reduces jitter to a small fraction of a sample period.
- Call it after block-mode data has been captured or when data has been retrieved from a previous block-mode capture. A 32-bit version of this function, ps2000aGetTriggerTimeOffset(), is also available.
- ⚠ manual note: the manual gives no numeric values for the `PS2000A_FS` ... `PS2000A_S` constants and no explanation of the suffixes beyond the constant names. The manual does not say what is returned (or which status) when the capture ended through the auto-trigger timeout instead of a trigger event; `PICO_NOT_USED_IN_THIS_CAPTURE_MODE` and `PICO_NO_SAMPLES_AVAILABLE` are listed without explanation.
- ⚠ manual note: the time-units enum is a pointer output (`PS2000A_TIME_UNITS * timeUnits`), so the unit may differ from call to call; the manual does not say how it is chosen.

picosdk: ps2000a.ps2000aGetTriggerTimeOffset64, argtypes = [c_int16, c_void_p, c_void_p, c_uint32], restype = c_uint32 (the same ctypes function object is also set as ps2000a._GetTriggerTimeOffset)
⚠ picosdk mismatch: the wrapper registers this C function under the python name `_GetTriggerTimeOffset` (and `_get_trigger_time_offset`); the 32-bit C function `ps2000aGetTriggerTimeOffset` (manual §3.15) is not wrapped. Argument list agrees with the manual.
picosdk enum (cross-check only; values are NOT in the manual): `ps2000a.PS2000A_TIME_UNITS` = {PS2000A_FS: 0, PS2000A_PS: 1, PS2000A_NS: 2, PS2000A_US: 3, PS2000A_MS: 4, PS2000A_S: 5, PS2000A_MAX_TIME_UNITS: 6}. The six names match the manual's list; `PS2000A_MAX_TIME_UNITS` is an extra name not in the manual.

### §3.65 ps2000aStop() – stop data capture (p. 115)

```c
    PICO_STATUS ps2000aStop
    (
      int16_t     handle
    )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |

**Returns**

- `PICO_OK`
- `PICO_INVALID_HANDLE`
- `PICO_USER_CALLBACK`
- `PICO_DRIVER_FUNCTION`

**Notes**

- Applicability: All modes.
- This function stops the scope device while it is waiting for a trigger or capturing data.
- · In block mode, you can optionally call ps2000aStop() to terminate the current capture. Any data in the buffer will be invalid.
- · In rapid block mode, you can optionally call ps2000aStop() to terminate the sequence of captures. Any completed captures will contain valid data but no further captures will be made.
- · In streaming mode, calling ps2000aStop() is the usual way to terminate data capture. If this function is called before a trigger event occurs, the oscilloscope may not contain valid data. If capture has already started, the buffer will contain valid data.
- ⚠ manual note: "Any data in the buffer will be invalid" (block mode) versus §2.6.1.1 steps 11 and 12 (Stop, then "Request new views of stored data"). The manual does not say whether data already transferred by ps2000aGetValues() into the user's buffer is affected, nor whether ps2000aStop() is required before a following ps2000aRunBlock().

picosdk: ps2000a.ps2000aStop, argtypes = [c_int16], restype = c_uint32 (the same ctypes function object is also set as ps2000a._Stop)

## Memory segments and captures (brief; phase 1 uses one segment)

### §3.29 ps2000aMemorySegments() – divide scope memory into segments (p. 64)

```c
   PICO_STATUS ps2000aMemorySegments
   (
     int16_t      handle
     uint32_t     nSegments,
     int32_t    * nMaxSamples
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `nSegments` | in | the number of segments required. Minimum: 1. Maximum: varies according to oscilloscope model – refer to datasheet. |
| `* nMaxSamples` | out | on exit, the number of samples available in each segment. This is the total number over all channels, so if two channels or 8-bit MSO ports are in use, the number of samples available to each channel is nMaxSamples divided by 2; and for 3 or 4 channels or MSO ports divide by 4. |

**Returns**

- `PICO_OK`
- `PICO_USER_CALLBACK`
- `PICO_INVALID_HANDLE`
- `PICO_TOO_MANY_SEGMENTS`
- `PICO_MEMORY`
- `PICO_DRIVER_FUNCTION`

**Notes**

- Applicability: Block mode, rapid block mode.
- This function sets the number of memory segments that the scope will use.
- When the scope is opened, the number of segments defaults to 1, meaning that each capture fills the scope's available memory. This function allows you to divide the memory into a number of segments so that the scope can store several waveforms sequentially.
- ⚠ manual note: the prototype has no comma after `handle`.
- ⚠ manual note: "if two channels or 8-bit MSO ports are in use, the number of samples available to each channel is nMaxSamples divided by 2; and for 3 or 4 channels or MSO ports divide by 4." is worded differently from §2.6.1 ("If any combination of one or two analog channels and one or two digital ports is enabled, each receives a quarter of the memory"); the manual does not reconcile the two for mixed analog/digital use.

picosdk: ps2000a.ps2000aMemorySegments, argtypes = [c_int16, c_uint32, c_void_p], restype = c_uint32 (the same ctypes function object is also set as ps2000a._MemorySegments)

### §3.47 ps2000aSetNoOfCaptures() – set number of captures to collect in one run (p. 84)

Not used in phase 1 (rapid block mode only).

```c
   PICO_STATUS ps2000aSetNoOfCaptures
   (
     int16_t     handle,
     uint32_t    nCaptures
   )
```

**Arguments**

| Name | Dir | Meaning (manual) |
|---|---|---|
| `handle` | in | device identifier returned by ps2000aOpenUnit(). |
| `nCaptures` | in | the number of waveforms to capture in one run. |

**Returns**

- `PICO_OK`
- `PICO_INVALID_HANDLE`
- `PICO_INVALID_PARAMETER`
- `PICO_DRIVER_FUNCTION`

**Notes**

- Applicability: Rapid block mode.
- This function sets the number of captures to be collected in one run of rapid block mode. If you do not call this function before a run, the driver will capture only one waveform. Once a value has been set, the value remains constant unless changed.

picosdk: ps2000a.ps2000aSetNoOfCaptures, argtypes = [c_int16, c_uint32], restype = c_uint32 (the same ctypes function object is also set as ps2000a._SetNoOfCaptures)


## Wrapper functions

### §3.67 Wrapper functions (p. 117)

The Software Development Kits (SDKs) for PicoScope devices contain wrapper dynamic link library (DLL) files in the lib subdirectory of your SDK installation for 32-bit and 64-bit systems. The wrapper functions provided by the wrapper DLLs are for use with programming languages such as MathWorks MATLAB, National Instruments LabVIEW and Microsoft Excel VBA that do not support features of the C programming language such as callback functions.

The source code contained in the Wrapper projects contains a description of the functions and the input and output parameters.

Below we explain the sequence of calls required to capture data in streaming mode using the wrapper API functions.

What concerns block mode: nothing. The only procedure in §3.67 (pp. 117 to 118, 13 numbered steps plus sub-steps) is for streaming mode (it calls ps2000aRunStreaming() and, for example, the wrapper functions setChannelCount, setEnabledChannels, setAppAndDriverBuffers, AvailableData and AutoStopped) and is not transcribed. The manual names no wrapper function for block mode.

---

# Part 3. Further information

### §4.1 Driver status codes (p. 119)

Every function in the ps2000a driver returns a driver status code from the list of PICO_STATUS values in PicoStatus.h, which is included in the inc folder of the PicoSDK installation.

⚠ manual note: that is the entire text of §4.1. The manual lists no `PICO_STATUS` numeric (hex) values anywhere, so none can be given here. The values are defined in `PicoStatus.h`, which is not in this repository. Where code needs a numeric status value, stop and say so (see "Open questions for hardware verification").

Status code names that the manual lists under "Returns" of the functions transcribed in this file (names exactly as the manual spells them; the manual gives no values and no per-code explanation):

| Status name | Listed under Returns of |
|---|---|
| `PICO_ANALOG_BOARD` | `ps2000aOpenUnit` |
| `PICO_BUFFERS_NOT_SET` | `ps2000aRunBlock`, `ps2000aGetValues` |
| `PICO_BUSY` | `ps2000aEnumerateUnits`, `ps2000aPingUnit`, `ps2000aFlashLed`, `ps2000aGetChannelInformation` |
| `PICO_CANCELLED` | `ps2000aIsReady` |
| `PICO_CONDITIONS` | `ps2000aSetSimpleTrigger` |
| `PICO_CONFIG_FAIL` | `ps2000aEnumerateUnits`, `ps2000aRunBlock` |
| `PICO_CONFIG_FAIL_AWG` | `ps2000aEnumerateUnits`, `ps2000aOpenUnit` |
| `PICO_DATA_NOT_AVAILABLE` | `ps2000aGetValues` |
| `PICO_DEVICE_SAMPLING` | `ps2000aGetValues`, `ps2000aGetTriggerTimeOffset64` |
| `PICO_DRIVER_FUNCTION` | `ps2000aCloseUnit`, `ps2000aGetUnitInfo`, `ps2000aPingUnit`, `ps2000aFlashLed`, `ps2000aGetChannelInformation`, `ps2000aGetAnalogueOffset`, `ps2000aSetChannel`, `ps2000aGetTimebase`, `ps2000aSetSimpleTrigger`, `ps2000aSetTriggerDelay`, `ps2000aRunBlock`, `ps2000aIsReady`, `ps2000aSetDataBuffer`, `ps2000aSetDataBuffers`, `ps2000aGetValues`, `ps2000aMaximumValue`, `ps2000aMinimumValue`, `ps2000aGetTriggerTimeOffset64`, `ps2000aStop`, `ps2000aMemorySegments`, `ps2000aSetNoOfCaptures` |
| `PICO_EEPROM_CORRUPT` | `ps2000aOpenUnit` |
| `PICO_ETS_NOT_RUNNING` | `ps2000aGetValues` |
| `PICO_FPGA_FAIL` | `ps2000aOpenUnit` |
| `PICO_FW_FAIL` | `ps2000aEnumerateUnits`, `ps2000aOpenUnit`, `ps2000aRunBlock` |
| `PICO_HANDLE_INVALID` | `ps2000aCloseUnit`, `ps2000aFlashLed`, `ps2000aGetChannelInformation` |
| `PICO_INFO_UNAVAILABLE` | `ps2000aGetUnitInfo` |
| `PICO_INITIALISE_FPGA` | `ps2000aEnumerateUnits`, `ps2000aOpenUnit` |
| `PICO_INVALID_ANALOGUE_OFFSET` | `ps2000aSetChannel` |
| `PICO_INVALID_CALL` | `ps2000aGetValues` |
| `PICO_INVALID_CHANNEL` | `ps2000aGetChannelInformation`, `ps2000aSetChannel`, `ps2000aGetTimebase`, `ps2000aSetSimpleTrigger`, `ps2000aRunBlock`, `ps2000aSetDataBuffer`, `ps2000aSetDataBuffers` |
| `PICO_INVALID_CONDITION_CHANNEL` | `ps2000aRunBlock` |
| `PICO_INVALID_COUPLING` | `ps2000aSetChannel` |
| `PICO_INVALID_HANDLE` | `ps2000aGetUnitInfo`, `ps2000aPingUnit`, `ps2000aGetAnalogueOffset`, `ps2000aSetChannel`, `ps2000aGetTimebase`, `ps2000aSetSimpleTrigger`, `ps2000aSetTriggerDelay`, `ps2000aRunBlock`, `ps2000aIsReady`, `ps2000aSetDataBuffer`, `ps2000aSetDataBuffers`, `ps2000aGetValues`, `ps2000aMaximumValue`, `ps2000aMinimumValue`, `ps2000aGetTriggerTimeOffset64`, `ps2000aStop`, `ps2000aMemorySegments`, `ps2000aSetNoOfCaptures` |
| `PICO_INVALID_INFO` | `ps2000aGetUnitInfo`, `ps2000aGetChannelInformation` |
| `PICO_INVALID_PARAMETER` | `ps2000aGetTimebase`, `ps2000aSetSimpleTrigger`, `ps2000aRunBlock`, `ps2000aSetDataBuffer`, `ps2000aSetDataBuffers`, `ps2000aGetValues`, `ps2000aSetNoOfCaptures` |
| `PICO_INVALID_SAMPLERATIO` | `ps2000aRunBlock`, `ps2000aGetValues` |
| `PICO_INVALID_TIMEBASE` | `ps2000aGetTimebase`, `ps2000aRunBlock` |
| `PICO_INVALID_TRIGGER_CHANNEL` | `ps2000aRunBlock` |
| `PICO_INVALID_VOLTAGE_RANGE` | `ps2000aGetAnalogueOffset`, `ps2000aSetChannel` |
| `PICO_KERNEL_DRIVER_TOO_OLD` | `ps2000aOpenUnit` |
| `PICO_MAX_UNITS_OPENED` | `ps2000aOpenUnit` |
| `PICO_MEMORY` | `ps2000aSetSimpleTrigger`, `ps2000aGetValues`, `ps2000aMaximumValue`, `ps2000aMinimumValue`, `ps2000aMemorySegments` |
| `PICO_MEMORY_CLOCK_FREQUENCY` | `ps2000aOpenUnit` |
| `PICO_MEMORY_FAIL` | `ps2000aEnumerateUnits`, `ps2000aOpenUnit` |
| `PICO_NOT_ENOUGH_SEGMENTS` | `ps2000aRunBlock` |
| `PICO_NOT_FOUND` | `ps2000aOpenUnit` |
| `PICO_NOT_RESPONDING` | `ps2000aOpenUnit`, `ps2000aPingUnit`, `ps2000aFlashLed`, `ps2000aGetChannelInformation`, `ps2000aRunBlock`, `ps2000aIsReady`, `ps2000aGetValues`, `ps2000aGetTriggerTimeOffset64` |
| `PICO_NOT_USED_IN_THIS_CAPTURE_MODE` | `ps2000aGetTriggerTimeOffset64` |
| `PICO_NO_SAMPLES_AVAILABLE` | `ps2000aIsReady`, `ps2000aGetValues`, `ps2000aGetTriggerTimeOffset64` |
| `PICO_NULL_PARAMETER` | `ps2000aEnumerateUnits`, `ps2000aOpenUnitProgress`, `ps2000aGetUnitInfo`, `ps2000aGetChannelInformation`, `ps2000aGetAnalogueOffset`, `ps2000aIsReady`, `ps2000aGetValues`, `ps2000aGetTriggerTimeOffset64` |
| `PICO_OK` | `ps2000aEnumerateUnits`, `ps2000aOpenUnit`, `ps2000aOpenUnitAsync`, `ps2000aOpenUnitProgress`, `ps2000aCloseUnit`, `ps2000aGetUnitInfo`, `ps2000aPingUnit`, `ps2000aFlashLed`, `ps2000aGetChannelInformation`, `ps2000aGetAnalogueOffset`, `ps2000aSetChannel`, `ps2000aGetTimebase`, `ps2000aSetSimpleTrigger`, `ps2000aSetTriggerDelay`, `ps2000aRunBlock`, `ps2000aIsReady`, `ps2000aSetDataBuffer`, `ps2000aSetDataBuffers`, `ps2000aGetValues`, `ps2000aMaximumValue`, `ps2000aMinimumValue`, `ps2000aGetTriggerTimeOffset64`, `ps2000aStop`, `ps2000aMemorySegments`, `ps2000aSetNoOfCaptures` |
| `PICO_OPEN_OPERATION_IN_PROGRESS` | `ps2000aOpenUnit`, `ps2000aOpenUnitAsync` |
| `PICO_OPERATION_FAILED` | `ps2000aOpenUnitAsync`, `ps2000aOpenUnitProgress` |
| `PICO_OS_NOT_SUPPORTED` | `ps2000aOpenUnit` |
| `PICO_PULSE_WIDTH_QUALIFIER` | `ps2000aRunBlock` |
| `PICO_RATIO_MODE_NOT_SUPPORTED` | `ps2000aSetDataBuffer`, `ps2000aSetDataBuffers`, `ps2000aGetValues` |
| `PICO_SEGMENT_OUT_OF_RANGE` | `ps2000aGetTimebase`, `ps2000aRunBlock`, `ps2000aSetDataBuffer`, `ps2000aSetDataBuffers`, `ps2000aGetValues`, `ps2000aGetTriggerTimeOffset64` |
| `PICO_STARTINDEX_INVALID` | `ps2000aRunBlock`, `ps2000aGetValues` |
| `PICO_TOO_MANY_SAMPLES` | `ps2000aGetTimebase`, `ps2000aRunBlock`, `ps2000aGetValues` |
| `PICO_TOO_MANY_SEGMENTS` | `ps2000aMaximumValue`, `ps2000aMinimumValue`, `ps2000aMemorySegments` |
| `PICO_TRIGGER_ERROR` | `ps2000aRunBlock` |
| `PICO_USER_CALLBACK` | `ps2000aCloseUnit`, `ps2000aSetChannel`, `ps2000aSetSimpleTrigger`, `ps2000aSetTriggerDelay`, `ps2000aRunBlock`, `ps2000aMaximumValue`, `ps2000aMinimumValue`, `ps2000aStop`, `ps2000aMemorySegments` |

⚠ manual note: `PICO_OK` is the only code the manual treats as success (it is listed first in every Returns list that names status codes and §3.34 says "This handle is valid only if the function returns PICO_OK"). The manual has no table explaining individual codes.

### §4.2 Enumerated types and constants (p. 119)

Enumerated types and constants are defined in ps2000aApi.h, which is included in the SDK under the inc folder. We recommend that you refer to these constants by name unless your programming language allows only numerical values.

⚠ manual note: that is the entire text of §4.2. The manual contains no table of enumerator values. `ps2000aApi.h` is not in this repository. The enumerations that appear in the sections transcribed above, and where their members are listed (names only unless noted):

| Type / constants | Members as listed by the manual | Where in this file |
|---|---|---|
| `PS2000A_CHANNEL` | `PS2000A_CHANNEL_A`, `PS2000A_CHANNEL_B`, `PS2000A_CHANNEL_C`, `PS2000A_CHANNEL_D` | §3.39 |
| digital ports (type of `channel` in §3.40/§3.41) | `PS2000A_DIGITAL_PORT0 = 0x80`, `PS2000A_DIGITAL_PORT1 = 0x81` (MSO models only) | §3.40, §3.41 |
| `PS2000A_COUPLING` | `PS2000A_AC`, `PS2000A_DC` | §3.39 |
| `PS2000A_RANGE` | `PS2000A_20MV`, `PS2000A_50MV`, `PS2000A_100MV`, `PS2000A_200MV`, `PS2000A_500MV`, `PS2000A_1V`, `PS2000A_2V`, `PS2000A_5V`, `PS2000A_10V`, `PS2000A_20V` | §3.39 |
| `PS2000A_THRESHOLD_DIRECTION` | 15 constants, `PS2000A_ABOVE` ... `PS2000A_NONE` | §3.56 (table from §3.58, p. 104) |
| `PS2000A_RATIO_MODE` | `PS2000A_RATIO_MODE_NONE`, `PS2000A_RATIO_MODE_AGGREGATE`, `PS2000A_RATIO_MODE_AVERAGE`, `PS2000A_RATIO_MODE_DECIMATE` | §3.18, §3.18.1 |
| `PS2000A_TIME_UNITS` | `PS2000A_FS`, `PS2000A_PS`, `PS2000A_NS`, `PS2000A_US`, `PS2000A_MS`, `PS2000A_S` | §3.16 |
| `PS2000A_CHANNEL_INFO` | `PS2000A_CI_RANGES` ("currently supported") | §3.7 |
| `PICO_INFO` | codes 0 to 10 with values given in the manual's table | §3.17 |
| `PS2000A_EXT_MIN_VALUE`, `PS2000A_EXT_MAX_VALUE` | –32 767 and +32 767 (digital values for –5 V and +5 V on the EXT input of some models) | §2.3 |
| `MAX_DELAY_COUNT` | named in §3.60 "Range: 0 to MAX_DELAY_COUNT"; value not given | §3.60 |

### §4.3 Numeric data types (p. 119)

Here is a list of the numeric data types used in the PicoScope 2000 Series A API:

| Type | Bits | Signed or unsigned? |
|---|---|---|
| int8_t | 8 | signed |
| int16_t | 16 | signed |
| uint16_t | 16 | unsigned |
| enum | 32 | enumerated |
| int32_t | 32 | signed |
| uint32_t | 32 | unsigned |
| float | 32 | signed (IEEE 754 binary32) |
| double | 64 | signed (IEEE 754 binary64) |
| int64_t | 64 | signed |
| uint64_t | 64 | unsigned |

⚠ manual note: `PICO_STATUS` is used as a return type throughout the manual but is not in this table; the manual does not give its width. The manual also does not list a Boolean type (`enabled` in ps2000aSetChannel() is `int16_t`).

---

## Not transcribed (out of phase 1 scope)

Everything below exists in the manual and was deliberately left out. Titles are the manual's own one-line descriptions (from its table of contents) with page numbers. A later phase should read the PDF for these.

### Rapid block mode

- §3.10 ps2000aGetNoOfCaptures() – get number of captures available (p. 39)
- §3.11 ps2000aGetNoOfProcessedCaptures() – get number of captures processed (p. 40)
- §3.20 ps2000aGetValuesBulk() – get data in rapid block mode (p. 53)
- §3.21 ps2000aGetValuesOverlapped() – set up data collection ahead of capture (p. 54)
- §3.22 ps2000aGetValuesOverlappedBulk() – set up data collection in rapid block mode (p. 56)
- §3.23 ps2000aGetValuesTriggerTimeOffsetBulk() – get rapid-block waveform times (32-bit) (p. 57)
- §3.24 ps2000aGetValuesTriggerTimeOffsetBulk64() – get rapid-block waveform times (64-bit) (p. 59)

Concepts: §2.6.2 Rapid block mode (p. 18), §2.6.2.1 Using rapid block mode, §2.6.2.2 Rapid block mode example 1: no aggregation (p. 19), §2.6.2.3 Rapid block mode example 2: using aggregation (p. 21), §3.21.1 Using the GetValuesOverlapped functions (p. 55).

### Streaming mode

- §3.12 ps2000aGetStreamingLatestValues() – get streaming data while scope is running (p. 41)
- §3.31 ps2000aNoOfStreamingValues() – get number of samples in streaming mode (p. 66)
- §3.38 ps2000aRunStreaming() – capture in streaming mode (p. 74)
- §3.66 ps2000aStreamingReady() – find out if streaming-mode data ready (p. 116)

Concepts: §2.6.4 Streaming mode (p. 25), §2.6.4.1 Using streaming mode (p. 26). The §3.67 wrapper procedure (p. 117) is also streaming-only.

### ETS (equivalent time sampling)

- §3.44 ps2000aSetEts() – set up equivalent-time sampling (p. 81)
- §3.45 ps2000aSetEtsTimeBuffer() – set up 64-bit buffer for ETS timings (p. 82)
- §3.46 ps2000aSetEtsTimeBuffers() – set up 32-bit buffers for ETS timings (p. 83)

Concepts: §2.6.3 ETS (Equivalent Time Sampling) (p. 23), §2.6.3.1 Using ETS mode (p. 24).

### Digital ports / MSO

- §3.42 ps2000aSetDigitalAnalogTriggerOperand() – set up combined analog/digital trigger (p. 79)
- §3.43 ps2000aSetDigitalPort() – set up digital input (p. 80)
- §3.49 ps2000aSetPulseWidthDigitalPortProperties() – set pulse-width triggering on digital inputs (p. 86)
- §3.61 ps2000aSetTriggerDigitalPortProperties() – set up digital channel trigger directions (p. 109)

Concepts: §2.4 MSO digital data (p. 12), §2.8 MSO digital connector (p. 29). Sub-section §3.61.1 PS2000A_DIGITAL_CHANNEL_DIRECTIONS structure (p. 110).

### Signal generator / AWG

- §3.51 ps2000aSetSigGenArbitrary() – set up arbitrary waveform generator (p. 90)
- §3.52 ps2000aSetSigGenBuiltIn() – set up standard signal generator (p. 95)
- §3.53 ps2000aSetSigGenBuiltInV2() – double-precision signal generator setup (p. 98)
- §3.54 ps2000aSetSigGenPropertiesArbitrary() – change AWG properties (p. 99)
- §3.55 ps2000aSetSigGenPropertiesBuiltIn() – change standard signal generator properties (p. 100)
- §3.62 ps2000aSigGenArbitraryMinMaxValues() – query AWG parameter limits (p. 112)
- §3.63 ps2000aSigGenFrequencyToPhase() – calculate AWG phase from frequency (p. 113)
- §3.64 ps2000aSigGenSoftwareControl() – trigger the signal generator (p. 114)

Sub-sections: §3.51.1 AWG index modes (p. 93), §3.51.2 Calculating deltaPhase (p. 94).

### Advanced triggers

- §3.57 ps2000aSetTriggerChannelConditions() – specify which channels to trigger on (p. 102)
- §3.58 ps2000aSetTriggerChannelDirections() – set up signal polarities for triggering (p. 104)
- §3.59 ps2000aSetTriggerChannelProperties() – set up trigger thresholds (p. 105)
- §3.27 ps2000aIsTriggerOrPulseWidthQualifierEnabled() – get trigger status (p. 62)
- §3.36 ps2000aQueryOutputEdgeDetect() – find out if state trigger edge-detection is enabled (p. 71)
- §3.48 ps2000aSetOutputEdgeDetect() – enable or disable state trigger edge-detection (p. 85)
- §3.25 ps2000aHoldOff() – not supported (p. 60)

Sub-sections: §3.57.1 PS2000A_TRIGGER_CONDITIONS structure (p. 103), §3.59.1 PS2000A_TRIGGER_CHANNEL_PROPERTIES structure (p. 106). Of §3.58 only the PS2000A_THRESHOLD_DIRECTION constants table is reproduced (under §3.56).

### Pulse width qualifier

- §3.50 ps2000aSetPulseWidthQualifier() – set up pulse width triggering (p. 87)

Sub-section: §3.50.1 PS2000A_PWQ_CONDITIONS structure (p. 89).

### Other functions not needed for single-shot block mode (data/segment helpers, 32-bit variants, async retrieval, callbacks)

- §3.3 ps2000aDataReady() – find out if post-collection data ready (p. 32)
- §3.8 ps2000aGetMaxDownSampleRatio() – get aggregation ratio for data (p. 37)
- §3.9 ps2000aGetMaxSegments() – find out how many segments allowed (p. 38)
- §3.15 ps2000aGetTriggerTimeOffset() – find out when trigger occurred (32-bit) (p. 45)
- §3.19 ps2000aGetValuesAsync() – get streaming data with callback (p. 52)



---

## picosdk 1.1 notes

Cross-check only. Everything in this section comes from the installed Python package `picosdk` 1.1 (`picosdk/library.py`, `constants.py`, `functions.py`, `errors.py`, `ps2000a.py`), not from the manual. None of it may be used as API documentation; it exists so that mismatches between the wrapper and the manual are visible.

### How `picosdk.library.Library._load` finds the shared library

`picosdk/ps2000a.py` defines `class Ps2000alib(Library)` whose `__init__` calls `super(Ps2000alib, self).__init__("ps2000a")`, and then creates the module-level instance `ps2000a = Ps2000alib()`. `Library.__init__` calls `self._load()` immediately, so importing `picosdk.ps2000a` without the native library raises an error. `_load` verbatim:

```python
    def _load(self):
        library_path = find_library(self.name)

        if library_path is None:
            env_var_name = "PATH" if sys.platform == 'win32' else "LD_LIBRARY_PATH"
            raise CannotFindPicoSDKError("PicoSDK (%s) not found, check %s" % (self.name, env_var_name))

        try:
            if sys.platform == 'win32':
                from ctypes import WinDLL
                result = WinDLL(library_path)
            else:
                from ctypes import cdll
                result = cdll.LoadLibrary(library_path)
        except OSError as e:
            raise CannotOpenPicoSDKError("PicoSDK (%s) not compatible (check 32 vs 64-bit): %s" % (self.name, e))
        return result
```

- Names tried: picosdk tries exactly one name, the bare string `"ps2000a"`, through `ctypes.util.find_library("ps2000a")` (imported in `library.py` as `from ctypes.util import find_library`). picosdk itself has no per-platform name list (no `ps2000a.dll`, `libps2000a.so`, ...). Which file names are searched is decided by the Python standard library (checked in the local Python 3.11 `ctypes/util.py`, not part of picosdk): on macOS `libps2000a.dylib`, `ps2000a.dylib`, `ps2000a.framework/ps2000a`; on Linux it looks for `libps2000a.so*` via the ldconfig cache, `gcc`/`cc` or `ld`; on Windows it searches `PATH` for `ps2000a.dll`.
- Environment variables: picosdk reads none itself. The error message for "not found" mentions `PATH` on win32 and `LD_LIBRARY_PATH` on every other platform (`sys.platform`).
- Loader: `ctypes.WinDLL` (stdcall) on win32, `ctypes.cdll.LoadLibrary` otherwise. A found-but-unloadable library raises `CannotOpenPicoSDKError` ("not compatible (check 32 vs 64-bit)"); not found raises `CannotFindPicoSDKError`.
- `Library.make_symbol(python_name, c_name, return_type, argument_types, docstring)` does `getattr(self._clib, c_name)`, sets `.restype` and `.argtypes` on the ctypes function, and registers it under three attribute names: the python name (for example `_RunBlock`), the C name (`ps2000aRunBlock`), and an underscore-ized name (`_run_block`). All `restype` values in `ps2000a.py` are `c_uint32` (the `PICO_STATUS`).
- Callback types are `ps2000a.BlockReadyType` and `ps2000a.StreamingReadyType`, made with `C_CALLBACK_FUNCTION_FACTORY`; there is no wrapper type for `ps2000aDataReady`.

### `picosdk.constants.PICO_STATUS` and `PICO_STATUS_LOOKUP`

- `PICO_STATUS` is a plain dict `{"PICO_OK": 0x00000000, "PICO_MAX_UNITS_OPENED": 0x00000001, ...}` mapping status names to integer values. It has 267 entries (from `"PICO_OK": 0x00000000` to `"PICO_SHADOW_CAL_CORRUPT": 0x10000007`).
- `PICO_STATUS_LOOKUP = {v: k for k, v in PICO_STATUS.items()}`, the reverse mapping from value to name (also 267 entries, so no two names share a value).
- `Library.__init__` exposes both (and `PICO_INFO`) on each driver object as `self.PICO_STATUS`, `self.PICO_STATUS_LOOKUP`, `self.PICO_INFO`.
- `constants.py` also defines `pico_tag(number)` (value to name, raises `UnknownConstantError`), `pico_num(tag)` (name to value) and `make_enum(members)` ("All C enums with no specific values follow the pattern 0, 1, 2... in the order they are in source.").
- The values below are picosdk's values for the status names the manual lists under Returns in the sections above (cross-check only; the manual gives no values). A name that is not a key of `PICO_STATUS` is shown in bold.

| Status name (as spelled in the manual) | picosdk `PICO_STATUS` value |
|---|---|
| `PICO_ANALOG_BOARD` | 0x00000052 |
| `PICO_BUFFERS_NOT_SET` | 0x00000046 |
| `PICO_BUSY` | 0x00000027 |
| `PICO_CANCELLED` | 0x0000003A |
| `PICO_CONDITIONS` | 0x00000022 |
| `PICO_CONFIG_FAIL` | 0x00000008 |
| `PICO_CONFIG_FAIL_AWG` | 0x00000053 |
| `PICO_DATA_NOT_AVAILABLE` | 0x00000018 |
| `PICO_DEVICE_SAMPLING` | 0x00000024 |
| `PICO_DRIVER_FUNCTION` | 0x00000043 |
| `PICO_EEPROM_CORRUPT` | 0x0000000A |
| `PICO_ETS_NOT_RUNNING` | 0x00000110 |
| `PICO_FPGA_FAIL` | 0x0000004E |
| `PICO_FW_FAIL` | 0x00000004 |
| `PICO_HANDLE_INVALID` | **not a key of picosdk PICO_STATUS** |
| `PICO_INFO_UNAVAILABLE` | 0x0000002A |
| `PICO_INITIALISE_FPGA` | 0x00000054 |
| `PICO_INVALID_ANALOGUE_OFFSET` | 0x00000050 |
| `PICO_INVALID_CALL` | 0x0000003C |
| `PICO_INVALID_CHANNEL` | 0x00000010 |
| `PICO_INVALID_CONDITION_CHANNEL` | 0x00000012 |
| `PICO_INVALID_COUPLING` | 0x00000045 |
| `PICO_INVALID_HANDLE` | 0x0000000C |
| `PICO_INVALID_INFO` | 0x00000029 |
| `PICO_INVALID_PARAMETER` | 0x0000000D |
| `PICO_INVALID_SAMPLERATIO` | 0x00000040 |
| `PICO_INVALID_TIMEBASE` | 0x0000000E |
| `PICO_INVALID_TRIGGER_CHANNEL` | 0x00000011 |
| `PICO_INVALID_VOLTAGE_RANGE` | 0x0000000F |
| `PICO_KERNEL_DRIVER_TOO_OLD` | 0x00000009 |
| `PICO_MAX_UNITS_OPENED` | 0x00000001 |
| `PICO_MEMORY` | 0x0000002D |
| `PICO_MEMORY_CLOCK_FREQUENCY` | 0x0000005B |
| `PICO_MEMORY_FAIL` | 0x00000002 |
| `PICO_NOT_ENOUGH_SEGMENTS` | 0x00000042 |
| `PICO_NOT_FOUND` | 0x00000003 |
| `PICO_NOT_RESPONDING` | 0x00000007 |
| `PICO_NOT_USED_IN_THIS_CAPTURE_MODE` | 0x0000005E |
| `PICO_NO_SAMPLES_AVAILABLE` | 0x00000025 |
| `PICO_NULL_PARAMETER` | 0x00000016 |
| `PICO_OK` | 0x00000000 |
| `PICO_OPEN_OPERATION_IN_PROGRESS` | 0x00000005 |
| `PICO_OPERATION_FAILED` | 0x00000006 |
| `PICO_OS_NOT_SUPPORTED` | 0x0000000B |
| `PICO_PULSE_WIDTH_QUALIFIER` | 0x0000001F |
| `PICO_RATIO_MODE_NOT_SUPPORTED` | 0x00000047 |
| `PICO_SEGMENT_OUT_OF_RANGE` | 0x00000026 |
| `PICO_STARTINDEX_INVALID` | 0x00000028 |
| `PICO_TOO_MANY_SAMPLES` | 0x0000001D |
| `PICO_TOO_MANY_SEGMENTS` | 0x0000001E |
| `PICO_TRIGGER_ERROR` | 0x0000002C |
| `PICO_USER_CALLBACK` | 0x00000023 |

⚠ picosdk mismatch: the manual's Returns lists for ps2000aCloseUnit (§3.2), ps2000aFlashLed (§3.5) and ps2000aGetChannelInformation (§3.7) spell the invalid-handle code `PICO_HANDLE_INVALID`; picosdk's `PICO_STATUS` has only `PICO_INVALID_HANDLE` (0x0000000C) and no `PICO_HANDLE_INVALID`.

### `picosdk.functions.adc2mV`, `mV2adc`, `assert_pico_ok` (quoted)

```python
def adc2mV(bufferADC, range, maxADC):
    """ 
        adc2mc(
                c_short_Array           bufferADC
                int                     range
                c_int32                 maxADC
                )
               
        Takes a buffer of raw adc count values and converts it into millivolts
    """

    channelInputRanges = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000]
    vRange = channelInputRanges[range]
    bufferV = [(x * vRange) / maxADC.value for x in bufferADC]

    return bufferV
```

`adc2mV` returns a list of millivolt values `(x * vRange) / maxADC.value`; `range` is used as a list index, so the helper assumes picosdk's own `PS2000A_RANGE` numbering (`PS2000A_10MV` = 0, `PS2000A_20MV` = 1, ...). `maxADC` must be a ctypes object with a `.value` attribute (for example a `c_int16` filled by `ps2000aMaximumValue`).

```python
def assert_pico_ok(status):
    """
        assert_pico_ok(
                        status
                       )
    """
    # checks for PICO_OK status return
    if status != PICO_STATUS['PICO_OK']:
        raise PicoSDKCtypesError("PicoSDK returned '{}'".format(PICO_STATUS_LOOKUP[status]))
```

`assert_pico_ok` raises `picosdk.errors.PicoSDKCtypesError` (a `PicoError` and `IOError`) with the status name when `status` is not `PICO_OK`; for a status value that is not a key of `PICO_STATUS_LOOKUP` the `PICO_STATUS_LOOKUP[status]` lookup itself raises `KeyError`.

`functions.mV2adc` exists:

```python
def mV2adc(millivolts, range, maxADC):
    """
        mV2adc(
                float                   millivolts
				int                     range
                c_int32                 maxADC
                )
        Takes a voltage value and converts it into adc counts
    """
    channelInputRanges = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000]
    vRange = channelInputRanges[range]
    adcValue = round((millivolts * maxADC.value)/vRange)

    return adcValue
```

(`functions.py` also contains `adc2mVpl1000`, `mV2adcpl1000`, `splitMSOData`, `splitMSODataFast`, and `assert_pico2000_ok`; those are not relevant to this driver.)

⚠ picosdk mismatch (scope of the helpers vs the manual): the manual gives no ADC-to-volts formula (see §2.3 ⚠ note). `adc2mV` / `mV2adc` use `value * range_mV / maxADC` and `round(mV * maxADC / range_mV)`, which is picosdk's own convention; `maxADC` there is meant to come from the driver's maximum-value call (manual §3.28, 32 512 per §2.3). Do not treat the formula as manual-confirmed.


---

## Open questions for hardware verification

Each item names the manual phrase that creates the question. The manual does not answer them; they must be settled by running the actual PicoScope 2207B MSO (or by an authoritative source the owner of this repository adds to this file), not by guessing.

1. **Which timebase table applies to the 2207B MSO (500 MS/s or 1 GS/s)?** §2.7 has two generic tables, "500 MS/s maximum sampling rate models:" and "1 GS/s maximum sampling rate models:", plus a table only for "PicoScope 2205 MSO:". The manual never says which table a 2207B MSO uses ("Refer to the oscilloscope data sheet for sampling rate specifications."). The sample interval of timebases 0 to 2 differs by a factor of 2 between the two tables. Verify with ps2000aGetTimebase2() for timebases 0, 1, 2, 3.
2. **Maximum sampling rate with one versus two analog channels enabled.** §2.7 footnote: "* Available only in single-channel mode." (on timebase 0) and "† The fastest available sampling rate may depend on which channels are enabled, and on the sampling mode." §2.6.1: "A PicoScope 2000 Series oscilloscope can sample at different rates according to the selected timebase and the combination of enabled channels." The manual does not say whether timebases 1 and 2 are also restricted with two channels, nor how the digital ports of an MSO affect this for the 2207B MSO (only the 2205 MSO has a digital-port footnote: "** Not available when channel B active, nor when channel A and both digital ports active."). Verify which timebases return `PICO_INVALID_TIMEBASE` (§3.13 Returns) with channel A only and with A and B enabled, with the digital ports disabled.
3. **Which voltage ranges does the 2207B MSO have?** §2.3: "You can set a device input channel to any voltage range from ±20 mV to ±20 V (subject to the device specification)". §3.39 lists `PS2000A_20MV` to `PS2000A_20V`. The manual has no model-specific range list. Verify with ps2000aGetChannelInformation() (`PS2000A_CI_RANGES`, §3.7), and verify that ps2000aSetChannel() returns `PICO_INVALID_VOLTAGE_RANGE` for an unsupported range. The numeric values of `PS2000A_RANGE`/`PS2000A_CI_RANGES` are not in the manual (item 16).
4. **ps2000aGetTimebase() or ps2000aGetTimebase2()?** §3.13: "If your programming language supports the float type, we recommend that you use ps2000aGetTimebase2() instead." §3.14: "returns the time interval as a float rather than a long. This allows it to return sub-nanosecond time intervals." The manual does not say whether the two functions can return different `maxSamples` or status codes, nor whether sub-nanosecond intervals occur on this model (timebase 0 of the 1 GS/s table is 1 ns).
5. **`maxSamples` at timebase 0 and in general.** §3.13: "The scope allocates a certain amount of memory for internal overheads and this may vary depending on the number of segments, number of channels enabled, and the timebase chosen." The manual gives no memory size for any model and no value of `maxSamples`; §3.29 `nMaxSamples` "is the total number over all channels". Verify by calling ps2000aGetTimebase() for timebase 0, 1, 2 and a slow timebase with one and two channels enabled, and compare with ps2000aMemorySegments() `nMaxSamples` (segments = 1).
6. **What does ps2000aGetValues() return for disabled channels?** §3.18: "If multiple channels are enabled, a single call to this function is sufficient to retrieve data for all channels." The manual says nothing about channels that are disabled or have no buffer registered, other than listing `PICO_BUFFERS_NOT_SET` in Returns. Verify: buffer contents, status, and `overflow` bits for a disabled channel with and without a registered buffer.
7. **`overflow` bit assignment.** §3.18: "It is a bit field with bit 0 denoting Channel A." The manual does not state the bits for Channel B, C, D or the digital ports. Verify with an over-range input on channel B only (expected by analogy, but not stated: bit 1).
8. **Is ps2000aCloseUnit() after ps2000aStop() required, and is ps2000aStop() needed after a completed block?** §2.2 step 7 "Stop capturing data." and step 8 "Close the scope unit."; §2.6.1.1 step 11 "Stop the oscilloscope using ps2000aStop()." and step 13 "Call ps2000aCloseUnit()."; §3.65: "In block mode, you can optionally call ps2000aStop() to terminate the current capture. Any data in the buffer will be invalid." The manual does not say whether CloseUnit stops a running capture, whether Stop is needed between two RunBlock calls (§2.6.1.1 step 10 "Repeat steps 5 to 9." has no Stop between runs), or whether ps2000aStop() invalidates data already copied with ps2000aGetValues() (step 12 "Request new views of stored data" follows step 11).
9. **Serial-string format returned by ps2000aEnumerateUnits().** §3.4: "a list of serial numbers separated by commas and terminated by a final null. Example: AQ005/139,VDR61/356,ZOR14/107"; `serialLth` "on entry, the length of the char buffer pointed to by serials; on exit, the length of the string written to serials". §3.17 `PICO_BATCH_AND_SERIAL` "Batch and serial number of device", example "KJL87/006". Open: whether the strings are identical, how big the buffer must be, what happens when it is too small, and whether ps2000aOpenUnit() `serial` accepts exactly one list element. Also "It does not detect units that already have a handle assigned to them by the driver." (so an already-opened unit disappears from the list).
10. **Open-by-serial behaviour.** §3.32: "If serial is NULL then the function opens the first scope found; otherwise, it tries to open the scope that matches the string." and `PICO_NOT_FOUND (if the specified unit was not found)`; `handle` is documented as "–1 : if the scope fails to open", "0 : if no scope is found" and "> 0 : a number that uniquely identifies the scope". Open: case sensitivity, how handle and status combine (for example whether `PICO_NOT_FOUND` comes with handle 0), what happens when the unit is already open in another process, and which status a unit that needs a different power supply or port returns (the manual lists no such code for this driver).
11. **Behaviour of `autoTrigger_ms` = 0 and non-zero.** §3.56: "autoTrigger_ms, the number of milliseconds the device will wait if no trigger occurs. If this is set to zero, the scope device will wait indefinitely for a trigger." and §3.37 `timeIndisposedMs`: "This does not include any auto trigger timeout." Open: the maximum value (`int16_t`), what the captured data and ps2000aGetTriggerTimeOffset64() return after an auto-trigger timeout (§3.16 lists `PICO_NOT_USED_IN_THIS_CAPTURE_MODE` and `PICO_NO_SAMPLES_AVAILABLE` without explanation), how a wait-forever capture is aborted (the only documented abort is ps2000aStop(), §3.65: "stops the scope device while it is waiting for a trigger or capturing data"), and whether `autoTrigger_ms` is honoured when `enable` is 0 ("zero to disable the trigger").
12. **Meaning of the `oversample` argument.** §3.13, §3.14 and §3.37 all say "oversample, not used", yet the manual's own rapid-block examples (p. 19, p. 21) pass `1` for it, and §3.18.1 says PS2000A_RATIO_MODE_AVERAGE is "Equivalent to the 'oversampling' function on older scopes." Open: which value is safe to pass (0 or 1) on this model, and whether the value must be the same in GetTimebase and RunBlock.
13. **Features the manual marks as model-dependent.** (a) Analog offset: ps2000aSetChannel() `analogOffset` "is ignored if the device is a PicoScope 2205 MSO"; ps2000aGetAnalogueOffset() applicability "All ps2000a units except the PicoScope 2205 MSO" and "If device does not support analog offset, zero will be returned." Open: whether the 2207B MSO supports analog offset and with which ranges. (b) EXT input: "External trigger input (PicoScope 2206, 2207 and 2208 only)" (§2.3) and §3.59 ps2000aSetTriggerChannelProperties() `channel`, p. 107 (not transcribed) "PS2000A_TRIGGER_EXT for the EXT input fitted to some models"; open: whether a 2207B MSO has an EXT input and whether it is a valid `source` for ps2000aSetSimpleTrigger(). (c) Number of memory segments: "Maximum: varies according to oscilloscope model – refer to datasheet." (§3.29). (d) Digital ports: "PS2000A_DIGITAL_PORT0 = 0x80 (MSO models only)" (§3.40).
14. **Memory partition for an MSO with a single analog channel.** §2.6.1: "if two channels are enabled, each receives half the memory" and "Note: The PicoScope MSO models behave differently. If only the two analog channels or only the two digital ports are enabled, each receives half the memory. If any combination of one or two analog channels and one or two digital ports is enabled, each receives a quarter of the memory." Open: memory (and thus the largest valid `noOfPreTriggerSamples` + `noOfPostTriggerSamples`) when exactly one analog channel and no digital port is enabled, and when the digital ports are disabled but were enabled earlier.
15. **Trigger time offset.** §3.16: "The time offset of a waveform is the delay from the trigger sampling instant to the time at which the driver estimates the waveform to have crossed the trigger threshold." Open: sign convention, the values/units returned in `timeUnits` for a given timebase, and the numeric values of the `PS2000A_FS` ... `PS2000A_S` constants (not in the manual).
16. **Numeric values of enums and status codes are not in the manual.** §4.1: "from the list of PICO_STATUS values in PicoStatus.h"; §4.2: "Enumerated types and constants are defined in ps2000aApi.h". Affected for this phase: `PS2000A_CHANNEL`, `PS2000A_COUPLING`, `PS2000A_RANGE`, `PS2000A_THRESHOLD_DIRECTION`, `PS2000A_RATIO_MODE`, `PS2000A_TIME_UNITS`, `PS2000A_CHANNEL_INFO` (`PS2000A_CI_RANGES`), every `PICO_STATUS` code, `MAX_DELAY_COUNT`, `TRUE`/`FALSE` for `enabled`. The only source in the repository is the picosdk cross-check (non-authoritative; it also disagrees with the manual's lists in places, see the ⚠ picosdk mismatch lines). The authoritative source is the vendor header (`ps2000aApi.h`, `PicoStatus.h`), which has not been added to this repository.
17. **Which `status` does the ps2000aBlockReady() callback receive, and what happens to a pending run on ps2000aStop()?** §3.1: "status, indicates whether an error occurred during collection of the data." The manual does not list values; §3.26 lists `PICO_CANCELLED` and `PICO_NO_SAMPLES_AVAILABLE` for ps2000aIsReady() without explanation. Verify the poll/callback result after (a) a normal trigger, (b) auto-trigger, (c) ps2000aStop() during a wait.
18. **Order of ps2000aSetDataBuffer() relative to ps2000aRunBlock().** §2.6.1.1 lists step 7 (SetDataBuffer) after step 6 (wait for ready) but says "(For greater efficiency when doing multiple captures, you can call this function outside the loop, after step 4.)"; the manual's rapid-block procedure (§2.6.2.1, p. 18) puts the buffer calls "between steps 7 and 8", i.e. before RunBlock, and §3.37 lists `PICO_BUFFERS_NOT_SET (in Overlapped mode)`. Open: whether buffers registered before ps2000aRunBlock() survive until ps2000aGetValues(), and whether changing channel settings or the timebase after registering invalidates them ("The data is lost when ... the settings are changed", §2.6.1).
19. **`bufferLth` and `noOfSamples` units.** §3.40: "bufferLth, the size of the buffer array" (samples or bytes is not stated); §3.18: "The number of samples retrieved will not be more than the number requested". Open: required relation between `bufferLth`, `noOfSamples` and `noOfPreTriggerSamples + noOfPostTriggerSamples`, and the status returned when the buffer is too small (`PICO_INVALID_PARAMETER` / `PICO_TOO_MANY_SAMPLES` are listed without explanation).
20. **Does GetTimebase have to precede RunBlock, and does it depend on SetChannel order?** §3.13: "The result depends on the number of channels enabled by the last call to ps2000aSetChannel()." §3.37 takes `timebase` directly. Open: whether a timebase accepted by ps2000aGetTimebase() with one channel enabled is still valid in ps2000aRunBlock() after a second channel is enabled (returns `PICO_INVALID_TIMEBASE` is listed for both).
21. **Variant string and channel count.** §3.17 gives `PICO_VARIANT_INFO` example `2206`; the format for a 2207B MSO is unknown. The fake treats a variant starting with `24` as 4-channel and everything else as 2-channel, and returns `PICO_INVALID_CHANNEL` for channels C and D on a 2-channel unit, whether `enabled` is 0 or 1 (§3.39 lists the code without saying when a disabled call is rejected). The plug tolerates that status only for a *disabled* channel 3 or 4 and records the channel count. Verify the string and the driver's reaction to disabling a channel the unit does not have.
22. **State of a freshly opened unit.** The manual does not say whether channels start enabled, what the trigger is, or whether buffers persist across `ps2000aOpenUnit()`. The fake starts with everything off.
23. **`ps2000aGetUnitInfo()` with an invalid handle.** §3.17: "If an invalid handle is passed, only the driver versions can be read." Which info codes work? The fake serves `PICO_DRIVER_VERSION` only.
24. **Statuses for out-of-range arguments.** Which status is returned for negative `noSamples`, negative pre/post counts in `ps2000aRunBlock()`, an out-of-range `threshold`, `delay` or `autoTrigger_ms` in `ps2000aSetSimpleTrigger()`, an unknown ratio-mode value, or a negative `startIndex`/`noOfSamples` in `ps2000aGetValues()`? The fake returns `PICO_INVALID_PARAMETER` throughout.
25. **`ps2000aRunBlock()` with no channel enabled.** §3.37 lists `PICO_INVALID_CHANNEL` without explanation. The fake returns it in this case, and `ps2000aGetTimebase2()` with no channel enabled is treated as one channel.
26. **`ps2000aGetTimebase2()` outputs on a non-OK status.** On `PICO_INVALID_TIMEBASE` the fake writes 0 to both outputs; on `PICO_TOO_MANY_SAMPLES` it fills both (extends the §3.13 ⚠ note).
27. **Trigger source not enabled.** `ps2000aSetSimpleTrigger()` on a disabled source: the fake returns `PICO_INVALID_TRIGGER_CHANNEL` (§3.37 lists it under `ps2000aRunBlock()` only); `ps2000aRunBlock()` also returns it if the source was disabled after the trigger was set.
28. **Disabled channel arguments.** A disabled channel in `ps2000aSetChannel()` still needs a valid coupling and range in the fake; the manual gives no "don't care" values. The plug sends `PS2000A_DC`, `PS2000A_1V`, `0.0` for disabled channels.
29. **`ps2000aSetSimpleTrigger()` with `enable = 0`.** §3.56: "enable, zero to disable the trigger". The fake and the plug assume the other arguments are ignored; the plug sends `PS2000A_CHANNEL_A`, `0`, `PS2000A_RISING`, `0`, `0`.
30. **Position of the trigger sample.** §3.37: "the maximum number of samples returned is always noOfPreTriggerSamples + noOfPostTriggerSamples" and §3.56 "delay, the time between the trigger occurring and the first sample being taken"; the manual does not state at which buffer index the trigger instant sits. The plug (`waveform_from_raw`) and the fake place it at index `noOfPreTriggerSamples` (`t = 0`), with `delay = 0`. Verify with a known edge on hardware; `ps2000aGetTriggerTimeOffset64()` (§3.16) gives the sub-sample residual.
