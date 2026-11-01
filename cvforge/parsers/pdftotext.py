"""poppler's pdftotext: reading-order mode (as simple screeners use it) and -layout mode."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class PdfToText:
    def __init__(self, layout: bool = False) -> None:
        self.layout = layout
        self.name = "pdftotext-layout" if layout else "pdftotext"
        # -layout keeps the page's visual columns, so side-by-side columns share lines.
        self.default_gate = not layout
        self.about = (
            "poppler, -layout: keeps visual columns on one line"
            if layout
            else "poppler, default reading order"
        )

    def unavailable(self) -> str | None:
        if shutil.which("pdftotext") is None:
            return "pdftotext is not on PATH; install poppler-utils."
        return None

    def extract(self, pdf: Path) -> str:
        cmd = ["pdftotext", "-enc", "UTF-8", *(["-layout"] if self.layout else []), str(pdf), "-"]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
        return proc.stdout
