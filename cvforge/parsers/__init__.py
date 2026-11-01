"""Text extractors behind one interface. Adding a parser is one module plus one line here."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from cvforge.parsers.pdftotext import PdfToText
from cvforge.parsers.plumber import PdfPlumber
from cvforge.parsers.pypdf_reader import PyPdf


class Parser(Protocol):
    name: str

    def unavailable(self) -> str | None:
        """None when usable, else the reason and how to fix it."""

    def extract(self, pdf: Path) -> str: ...


def all_parsers() -> list[Parser]:
    return [PdfToText(), PdfPlumber(), PyPdf()]
