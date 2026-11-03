"""poppler's pdftotext: reading-order mode (as simple screeners use it) and -layout mode."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from cvforge.platforms import install_command


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
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
        return proc.stdout
