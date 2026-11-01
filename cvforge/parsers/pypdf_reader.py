"""pypdf: pure-Python extractor with its own text-ordering logic, independent of poppler.

Layout mode is used. pypdf's default mode inserts a space at most kerning pairs in TeX output
("T echnical W riter"), whatever the font, so a miss there carries no signal about the template.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


class PyPdf:
    name = "pypdf"

    def unavailable(self) -> str | None:
        if importlib.util.find_spec("pypdf") is None:
            return "pypdf is not installed; pip install 'cvforge[check]'."
        return None

    def extract(self, pdf: Path) -> str:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf))
        return "\n".join(page.extract_text(extraction_mode="layout") or "" for page in reader.pages)
