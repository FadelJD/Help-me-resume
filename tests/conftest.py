from __future__ import annotations

import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
EXAMPLES = ROOT / "examples"
TEMPLATES = ROOT / "templates"

# `tex`: needs a TeX engine (latexmk is optional; compile runs the engine itself without it).
# `poppler`: needs pdftotext, which is not installed by default on Windows.
HAVE_TEX = shutil.which("pdflatex") is not None
HAVE_POPPLER = shutil.which("pdftotext") is not None


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    no_tex = pytest.mark.skip(reason="no TeX engine (pdflatex) on PATH; run `cvforge doctor`")
    no_poppler = pytest.mark.skip(reason="pdftotext (poppler) not on PATH; run `cvforge doctor`")
    for item in items:
        if "tex" in item.keywords and not HAVE_TEX:
            item.add_marker(no_tex)
        if "poppler" in item.keywords and not HAVE_POPPLER:
            item.add_marker(no_poppler)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="Rewrite tests/golden/ from the current renderer (say why in the commit message).",
    )
