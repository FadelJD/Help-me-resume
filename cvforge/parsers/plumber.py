"""pdfplumber (pdfminer.six underneath): character-level extraction; shows unmapped glyphs."""

from __future__ import annotations

import importlib.util
from pathlib import Path


class PdfPlumber:
    name = "pdfplumber"

    def unavailable(self) -> str | None:
        if importlib.util.find_spec("pdfplumber") is None:
            return "pdfplumber is not installed; pip install 'cvforge[check]'."
        return None

    def extract(self, pdf: Path) -> str:
        import pdfplumber

        with pdfplumber.open(str(pdf)) as doc:
            return "\n".join(page.extract_text() or "" for page in doc.pages)
