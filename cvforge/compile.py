"""latexmk wrapper. Returns the PDF path or raises with the LaTeX error and its line."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from cvforge.errors import CVForgeError, Issue


def latexmk_available() -> bool:
    return shutil.which("latexmk") is not None


ENGINES = {"pdflatex": "-pdf", "xelatex": "-xelatex", "lualatex": "-lualatex"}


def search_env(search: Sequence[Path]) -> dict[str, str]:
    """Environment that lets TeX find a template's own .cls/.sty files and fonts.

    Each folder is searched recursively (`//`); the trailing separator keeps TeX's defaults.
    """
    env = dict(os.environ)
    if not search:
        return env
    dirs = os.pathsep.join(f"{p.resolve()}//" for p in search) + os.pathsep
    for var in ("TEXINPUTS", "OPENTYPEFONTS", "TTFONTS", "TFMFONTS", "T1FONTS", "ENCFONTS"):
        env[var] = dirs + env.get(var, "")
    return env


def compile_pdf(
    tex: Path, timeout: int = 180, engine: str = "pdflatex", search: Sequence[Path] = ()
) -> Path:
    if not latexmk_available():
        raise CVForgeError(
            [
                Issue(
                    file=str(tex),
                    message="latexmk is not on PATH, so the PDF cannot be built.",
                    fix="install TeX Live (Debian/Ubuntu: apt-get install latexmk "
                    "texlive-latex-extra texlive-fonts-recommended lmodern).",
                )
            ]
        )
    tex = tex.resolve()
    cmd = [
        "latexmk",
        ENGINES[engine],
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        f"-outdir={tex.parent}",
        tex.name,
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=tex.parent,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=search_env(search),
        )
    except subprocess.TimeoutExpired as exc:
        raise CVForgeError(
            [
                Issue(
                    file=str(tex),
                    message=f"latexmk did not finish within {timeout}s.",
                    fix="compile it by hand with `latexmk -pdf` to see where it hangs.",
                )
            ]
        ) from exc
    pdf = tex.with_suffix(".pdf")
    if proc.returncode != 0 or not pdf.exists():
        log = tex.with_suffix(".log")
        text = log.read_text(errors="replace") if log.exists() else proc.stdout + proc.stderr
        line, message = parse_log_error(text)
        raise CVForgeError(
            [
                Issue(
                    file=str(tex),
                    line=line,
                    message=f"LaTeX error: {message}",
                    fix=f"see {log.name}; if the line holds profile text, check its escaping, "
                    "otherwise fix the template at that line.",
                )
            ]
        )
    return pdf


def parse_log_error(log: str) -> tuple[int | None, str]:
    m = re.search(r"^[^\n:]*\.tex:(\d+): (.+)$", log, flags=re.MULTILINE)
    if m:
        return int(m.group(1)), m.group(2).strip()
    m = re.search(r"^! (.+)$", log, flags=re.MULTILINE)
    line = re.search(r"^l\.(\d+)", log, flags=re.MULTILINE)
    if m:
        return (int(line.group(1)) if line else None), m.group(1).strip()
    return None, "latexmk failed; no error line found in the log."
