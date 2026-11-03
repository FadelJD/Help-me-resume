"""poppler's pdftotext: reading-order mode (as simple screeners use it) and -layout mode."""

from __future__ import annotations

import shutil
from pathlib import Path

from cvforge.platforms import install_command, run_tool


class PdfToText:
    def __init__(self, layout: bool = False) -> None:
        self.layout = layout
        self.name = "pdftotext-layout" if layout else "pdftotext"
        self.about = (
            "poppler, -layout: keeps visual columns on one line"
            if layout
            else "poppler, default reading order"
        )

    def unavailable(self) -> str | None:
        if shutil.which("pdftotext") is None:
            return (
                f"not installed (pdftotext, from poppler); install: {install_command('pdftotext')}"
            )
        return None

    def extract(self, pdf: Path) -> str:
        cmd = ["pdftotext", "-enc", "UTF-8", *(["-layout"] if self.layout else []), str(pdf), "-"]
        return run_tool(cmd, cwd=pdf.parent, timeout=60, check=True).stdout
