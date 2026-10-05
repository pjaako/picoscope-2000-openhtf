"""OpenHTF plug for PicoScope 2000 Series (A API) USB oscilloscopes.

The plug names (`PicoScope2000Plug`, `Waveform`, ...) are resolved lazily, on first access, so
that importing a light submodule such as `picoscope_2000_openhtf.fake_resource` does not pull in
`openhtf` or `picosdk` (SPEC §6: the fake imports only numpy and the standard library).
`picosdk.ps2000a` is never imported here in any case (`tests/test_import.py`).
"""

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

from .capture import Capture, Channel, Edge
from .measure import ClippedError

if TYPE_CHECKING:
    from .plug import (
        CaptureError,
        PicoError,
        PicoScope2000Plug,
        Waveform,
        WaveformMeta,
        waveform_from_raw,
    )

try:
    __version__ = version("picoscope-2000-openhtf")  # pyproject.toml is the single source of truth
except PackageNotFoundError:  # pragma: no cover - not installed
    __version__ = "0.0.0"

_FROM_PLUG = (
    "CaptureError",
    "PicoError",
    "PicoScope2000Plug",
    "Waveform",
    "WaveformMeta",
    "waveform_from_raw",
)

__all__ = [
    "Capture",
    "CaptureError",
    "Channel",
    "ClippedError",
    "Edge",
    "PicoError",
    "PicoScope2000Plug",
    "Waveform",
    "WaveformMeta",
    "__version__",
    "waveform_from_raw",
]


def __getattr__(name: str) -> Any:
    if name in _FROM_PLUG:
        value = getattr(import_module(".plug", __name__), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
