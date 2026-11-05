"""Text extractors behind one interface. Adding a parser is one module plus one line here.

A gating parser's misses fail `check`; an advisory parser's misses are reported as warnings with
the string it returned instead. Which parsers gate depends on the OS (DEFAULT_GATES): Windows has
no poppler by default, so PDFium takes pdftotext's place there. `[parsers.<name>]` in
cvforge.toml overrides `gate` and `enabled` per parser.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from cvforge.parsers.pdfium import Pdfium
from cvforge.parsers.pdfminer_hl import PdfMiner
from cvforge.parsers.pdftotext import PdfToText
from cvforge.parsers.plumber import PdfPlumber
from cvforge.parsers.pypdf_reader import PyPdf
from cvforge.platforms import OS, current_os


class Parser(Protocol):
    name: str
    about: str

    def unavailable(self) -> str | None:
        """None when usable, else the reason and how to fix it."""

    def extract(self, pdf: Path) -> str: ...


def all_parsers() -> list[Parser]:
    return [
        PdfToText(layout=False),
        PdfToText(layout=True),
        PdfPlumber(),
        PyPdf(layout=True),
        PyPdf(layout=False),
        PdfMiner(),
        Pdfium(),
    ]


PARSER_NAMES = [p.name for p in all_parsers()]

# Readers whose misses fail `check`, per OS. Everything else is advisory.
DEFAULT_GATES: dict[str, frozenset[str]] = {
    "linux": frozenset({"pdftotext", "pdfplumber", "pypdf-layout"}),
    "macos": frozenset({"pdftotext", "pdfplumber", "pypdf-layout"}),
    "windows": frozenset({"pdfplumber", "pypdf-layout", "pdfium"}),
}


def default_gates(os_name: OS | None = None) -> frozenset[str]:
    return DEFAULT_GATES[os_name or current_os()]
