"""pdfminer.six's high-level `extract_text`: the call Resume Matcher, markitdown and pyresparser
make. It reads differently from pdfplumber's default `extract_text()` on some fonts, so it is a
separate reading. Advisory by default (docs/research.md)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from cvforge.platforms import install_command


class PdfMiner:
    name = "pdfminer"
    about = "pdfminer.six high-level extract_text (Resume Matcher, markitdown, pyresparser)"

    def unavailable(self) -> str | None:
        if importlib.util.find_spec("pdfminer") is None:
            return f"not installed (pdfminer); install: {install_command('pdfminer')}"
        return None

    def extract(self, pdf: Path) -> str:
        from pdfminer.high_level import extract_text

        text: str = extract_text(str(pdf))
        return text
