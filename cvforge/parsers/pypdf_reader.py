"""pypdf: pure-Python extractor with its own text-ordering logic, independent of poppler.

Two adapters. `pypdf-layout` gates. `pypdf` (default mode, the one LangChain's PyPDFLoader and
many quick screening scripts call) is advisory: in TeX output it inserts a space inside most
kerning pairs ("T echnical W riter") in every font tried, so its misses are reported as warnings
that show what a pipeline built on it would read.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from cvforge.platforms import install_command


class PyPdf:
    def __init__(self, layout: bool) -> None:
        self.layout = layout
        self.name = "pypdf-layout" if layout else "pypdf"
        self.about = (
            "pypdf, layout mode"
            if layout
            else "pypdf, default mode (LangChain PyPDFLoader); splits kerning pairs"
        )

    def unavailable(self) -> str | None:
        if importlib.util.find_spec("pypdf") is None:
            return f"not installed (pypdf); install: {install_command('pypdf')}"
        return None

    def extract(self, pdf: Path) -> str:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf))
        if self.layout:
            return "\n".join(
                page.extract_text(extraction_mode="layout") or "" for page in reader.pages
            )
        return "\n".join(page.extract_text() or "" for page in reader.pages)
