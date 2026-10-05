import json
import subprocess
import sys

import picoscope_2000_openhtf


def test_import_exposes_version() -> None:
    assert isinstance(picoscope_2000_openhtf.__version__, str)
    assert picoscope_2000_openhtf.__version__


def test_version_comes_from_package_metadata() -> None:
    from importlib.metadata import version

    assert picoscope_2000_openhtf.__version__ == version("picoscope-2000-openhtf")


def test_import_does_not_load_picosdk_ps2000a() -> None:
    # picosdk.ps2000a raises at import time when the native library is absent (as in CI),
    # so importing the package must never pull it in.
    code = (
        "import json, sys\n"
        "import picoscope_2000_openhtf\n"
        "print(json.dumps({'loaded': 'picosdk.ps2000a' in sys.modules}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {"loaded": False}
