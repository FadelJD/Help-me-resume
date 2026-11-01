from __future__ import annotations

import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
EXAMPLES = ROOT / "examples"
TEMPLATES = ROOT / "templates"

HAVE_TEX = shutil.which("latexmk") is not None and shutil.which("pdftotext") is not None


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    skip = pytest.mark.skip(reason="latexmk/pdftotext not on PATH")
    for item in items:
        if "tex" in item.keywords and not HAVE_TEX:
            item.add_marker(skip)
