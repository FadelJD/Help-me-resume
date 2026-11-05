"""PDFium (Chrome's PDF engine) via pypdfium2: an independent codebase from poppler, pdfminer and
pypdf; Docling and other document pipelines use it. Advisory by default (docs/research.md)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

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


def layout_text(pdf: Path) -> str:
    """Text laid out like `pdftotext -layout`, rebuilt from PDFium's character boxes: one line per
    visual line, leading spaces for indentation, and three or more spaces where a wide gap
    separates columns (a title on the left, its dates on the right). Pages are joined by a form
    feed. `cvforge import` uses this when pdftotext is not installed."""
    import pypdfium2

    doc = pypdfium2.PdfDocument(str(pdf))
    pages: list[str] = []
    try:
        for index in range(len(doc)):
            pages.append(_page_layout(doc[index].get_textpage()))
    finally:
        doc.close()
    return "\f".join(pages)


Segment = tuple[str, float, float, float]  # text, left, right, centre y


def _segments(tp: Any) -> tuple[list[Segment], float]:
    """PDFium's own lines (it decides word spaces and line ends), each with its extent, split
    where two characters are further apart than a column gap. Returns them and the text size."""
    segments: list[Segment] = []
    heights: list[float] = []
    text, left, right = "", 0.0, 0.0
    ys: list[float] = []

    def close() -> None:
        nonlocal text, ys
        if text.strip():
            ys.sort()
            segments.append((text.strip(), left, right, ys[len(ys) // 2]))
        text, ys = "", []

    boxes: list[tuple[str, tuple[float, float, float, float]]] = []
    for i in range(tp.count_chars()):
        ch = tp.get_text_range(i, 1).replace("\ufffe", "-").replace("\x02", "-")
        box = tp.get_charbox(i)
        boxes.append((ch, box))
        if box[2] > box[0] and not ch.isspace():
            heights.append(box[3] - box[1])
    heights.sort()
    size = heights[len(heights) // 2] if heights else 10.0
    for ch, (b_left, bottom, b_right, top) in boxes:
        if ch in ("\r", "\n", ""):
            close()
            continue
        ink = b_right > b_left and not ch.isspace()
        if ink and text.strip() and b_left - right > size * 2.5:
            close()
        if ink:
            if not text.strip():
                left = b_left
            right = b_right
            ys.append((top + bottom) / 2)
        if text or ink:
            text += ch
    close()
    return segments, size


def _page_layout(textpage: object) -> str:
    segments, size = _segments(textpage)
    if not segments:
        return ""
    lines: list[list[Segment]] = []
    for seg in sorted(segments, key=lambda s: -s[3]):
        if lines and abs(lines[-1][0][3] - seg[3]) <= size * 0.6:
            lines[-1].append(seg)
        else:
            lines.append([seg])
    margin = min(seg[1] for seg in segments)
    out: list[str] = []
    for line in lines:
        line.sort(key=lambda s: s[1])
        text = " " * round((line[0][1] - margin) / size)
        for n, (part, left, _right, _y) in enumerate(line):
            if n:
                gap = left - line[n - 1][2]
                text += "   " if gap > size * 2.5 else " "
            text += part
        out.append(text.rstrip())
    return "\n".join(out)
