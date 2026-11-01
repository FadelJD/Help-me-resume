"""poppler's pdftotext in its default reading-order mode, as simple screeners use it."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class PdfToText:
    name = "pdftotext"

    def unavailable(self) -> str | None:
        if shutil.which("pdftotext") is None:
            return "pdftotext is not on PATH; install poppler-utils."
        return None

    def extract(self, pdf: Path) -> str:
        proc = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", str(pdf), "-"],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return proc.stdout
