"""Which OS we are on, and the exact install command for each tool on it.

One table, used by `cvforge doctor`, by readers that are not installed and by compile when no TeX
engine is found. The Windows package ids (winget, scoop, choco) are not verified on a Windows
machine from this repository's CI; see docs/windows.md for what has and has not been tested.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

OS = Literal["windows", "macos", "linux"]


def run_tool(
    cmd: Sequence[str],
    *,
    cwd: Path,
    timeout: int = 60,
    env: Mapping[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Every external program cvforge runs goes through here: an argument list (never a shell),
    an explicit working folder, and UTF-8 output decoded leniently (TeX and poppler can emit
    invalid bytes, and Windows consoles would otherwise decode with a legacy code page)."""
    return subprocess.run(
        list(cmd),
        cwd=cwd,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=check,
        env=None if env is None else dict(env),
        shell=False,
    )


def current_os() -> OS:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def os_label(os_name: OS | None = None) -> str:
    os_name = os_name or current_os()
    if os_name == "linux":
        try:
            info = platform.freedesktop_os_release()
            return f"Linux ({info.get('PRETTY_NAME', 'unknown distribution')})"
        except OSError:
            return "Linux"
    return {"windows": "Windows", "macos": "macOS"}[os_name] + f" {platform.release()}"


def debian_family() -> bool:
    return shutil.which("apt-get") is not None


PIP_CHECK = 'pip install "cvforge[check]"  (or, if installed with pipx: pipx inject cvforge {pkg})'

# tool -> os -> command. Several Windows managers are given because people use different ones.
INSTALL: dict[str, dict[str, str]] = {
    "tex": {
        "windows": "winget install MiKTeX.MiKTeX  (or: scoop install miktex; choco install miktex;"
        " or TeX Live from https://tug.org/texlive/windows.html)",
        "macos": "brew install --cask mactex-no-gui",
        "linux": "sudo apt-get install -y texlive-latex-base texlive-latex-extra "
        "texlive-fonts-recommended lmodern",
    },
    "latexmk": {
        "windows": "MiKTeX: mpm --install=latexmk (needs Perl: winget install StrawberryPerl."
        "StrawberryPerl); TeX Live includes it. Optional: cvforge runs the engine without it.",
        "macos": "included in MacTeX (optional: cvforge runs the engine without it)",
        "linux": "sudo apt-get install -y latexmk  (optional: cvforge runs the engine without it)",
    },
    "pdftotext": {
        "windows": "winget install oschwartz10612.Poppler  (or: scoop install poppler; "
        "choco install poppler)",
        "macos": "brew install poppler",
        "linux": "sudo apt-get install -y poppler-utils",
    },
    "python": {
        "windows": "winget install Python.Python.3.12",
        "macos": "brew install python@3.12",
        "linux": "sudo apt-get install -y python3 python3-venv pipx",
    },
    "semantic": {
        "windows": 'pip install "cvforge[semantic]", then download the model once with network',
        "macos": 'pip install "cvforge[semantic]", then download the model once with network',
        "linux": 'pip install "cvforge[semantic]", then download the model once with network',
    },
}

PYTHON_PACKAGES = {
    "pdfplumber": "pdfplumber",
    "pypdf": "pypdf",
    "pypdfium2": "pypdfium2",
    "pdfminer": "pdfminer.six",
}


def install_command(tool: str, os_name: OS | None = None) -> str:
    os_name = os_name or current_os()
    if tool in PYTHON_PACKAGES:
        return PIP_CHECK.format(pkg=PYTHON_PACKAGES[tool])
    command = INSTALL[tool][os_name]
    if tool in ("pdftotext", "tex") and os_name == "linux" and not debian_family():
        return command + "  (Debian/Ubuntu shown; use your distribution's package manager)"
    return command
