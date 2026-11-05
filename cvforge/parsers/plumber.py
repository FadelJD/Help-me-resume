"""pdfplumber (pdfminer.six underneath): character-level extraction; shows unmapped glyphs."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from cvforge.platforms import install_command


class PdfPlumber:
    name = "pdfplumber"
    about = "pdfminer.six; prints unmapped glyphs as (cid:N)"

    def unavailable(self) -> str | None:
        if importlib.util.find_spec("pdfplumber") is None:
            return f"not installed (pdfplumber); install: {install_command('pdfplumber')}"
        return None

    def extract(self, pdf: Path) -> str:
        import pdfplumber

        with pdfplumber.open(str(pdf)) as doc:
            return "\n".join(page.extract_text() or "" for page in doc.pages)
