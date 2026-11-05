"""The README's install blocks are what install-test runs; keep their promised shape."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _extractor() -> ModuleType:
    path = ROOT / ".github" / "scripts" / "readme_commands.py"
    spec = importlib.util.spec_from_file_location("readme_commands", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("os_name", ["linux", "windows"])
def test_install_block_and_quick_start_extract(os_name: str) -> None:
    install, quick = _extractor().commands(README, os_name)
    assert install[-1] == "cvforge doctor"
    assert quick[-1] == "cvforge check out/cv.tex"


def test_windows_script_installs_the_checkout_and_skips_winget() -> None:
    script = _extractor().script(README, "windows")
    assert 'pipx install "$($env:REPO)[check]"' in script
    assert "git+https://" not in script
    runs = [ln for ln in script.splitlines() if not ln.startswith(("#", "Write-Host"))]
    assert not any(ln.startswith("winget") for ln in runs)


def test_linux_script_installs_the_checkout() -> None:
    script = _extractor().script(README, "linux")
    assert script.startswith("set -euxo pipefail\n")
    assert 'pipx install "$REPO[check]"' in script
    assert "git+https://" not in script


def test_windows_reader_set_is_explained() -> None:
    assert "On Windows they are pdfplumber, pypdf in layout mode and PDFium" in README
    assert "](docs/windows.md)" in README
    windows = (ROOT / "docs" / "windows.md").read_text(encoding="utf-8")
    assert "pdftotext never has to pass on Windows" in windows


# Em and en dashes read as machine-written; ordinary English phrasing is left to the writer.
STYLE_RULES = {
    "em dash": "\u2014",
    "en dash": "\u2013",
}


@pytest.mark.parametrize("doc", ["README.md", "docs/windows.md"])
def test_docs_have_no_em_or_en_dashes(doc: str) -> None:
    text = (ROOT / doc).read_text(encoding="utf-8")
    prose = re.sub(r"```.*?```", "", text, flags=re.S)  # commands may contain anything
    found = [
        f"{name}: {m.group(0)!r}"
        for name, pattern in STYLE_RULES.items()
        for m in re.finditer(pattern, prose, flags=re.I)
    ]
    assert not found, f"{doc}: " + "; ".join(found)


def test_quick_start_commands_run_in_both_shells() -> None:
    _, quick = _extractor().commands(README, "linux")
    assert not any("&&" in ln for ln in quick), "Windows PowerShell 5.1 has no &&"
