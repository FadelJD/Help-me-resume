"""PDFium (Chrome's PDF engine) via pypdfium2: an independent codebase from poppler, pdfminer and
pypdf; Docling and other document pipelines use it. Advisory by default (docs/research.md)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from cvforge.platforms import install_command


class Pdfium:
    name = "pdfium"
    about = "PDFium via pypdfium2 (Chrome's engine); independent of the others"

    def unavailable(self) -> str | None:
        if importlib.util.find_spec("pypdfium2") is None:
            return f"not installed (pypdfium2); install: {install_command('pypdfium2')}"
        return None

    def extract(self, pdf: Path) -> str:
        import pypdfium2

        doc = pypdfium2.PdfDocument(str(pdf))
        try:
            pages = [doc[i].get_textpage().get_text_range() for i in range(len(doc))]
        finally:
            doc.close()
        text = "\n".join(pages).replace("\r\n", "\n").replace("\r", "\n")
        # PDFium marks a hyphen that TeX inserted at a line end as U+FFFE (or U+0002).
        return text.replace("￾", "-").replace("\x02", "-")
