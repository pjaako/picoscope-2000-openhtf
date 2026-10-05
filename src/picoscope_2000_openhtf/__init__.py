"""OpenHTF plug for PicoScope 2000 Series (A API) USB oscilloscopes."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("picoscope-2000-openhtf")  # pyproject.toml is the single source of truth
except PackageNotFoundError:  # pragma: no cover - not installed
    __version__ = "0.0.0"

__all__ = ["__version__"]
