from __future__ import annotations

from pathlib import Path

import pytest

from cvforge.compile import compile_pdf, parse_log_error
from cvforge.errors import CVForgeError


@pytest.mark.tex
def test_compile_ok(tmp_path: Path) -> None:
    tex = tmp_path / "ok.tex"
    tex.write_text("\\documentclass{article}\\begin{document}Hello\\end{document}\n")
    assert compile_pdf(tex).exists()


@pytest.mark.tex
def test_compile_error_names_line(tmp_path: Path) -> None:
    tex = tmp_path / "bad.tex"
    tex.write_text("\\documentclass{article}\n\\begin{document}\n\\nosuchmacro\n\\end{document}\n")
    with pytest.raises(CVForgeError) as exc:
        compile_pdf(tex)
    issue = exc.value.issues[0]
    assert issue.line == 3
    assert "Undefined control sequence" in issue.message


def test_parse_log_error_fallback() -> None:
    assert parse_log_error("! Missing $ inserted.\nl.12 foo") == (12, "Missing $ inserted.")
    assert parse_log_error("nothing useful")[0] is None


@pytest.mark.tex
def test_compile_survives_tex_splitting_utf8_in_its_output(tmp_path: Path) -> None:
    # Regression (found by the escaper fuzz): TeX wraps output lines at a fixed byte width,
    # cutting multi-byte characters in half; strict decoding crashed the build.
    long_line = ("Ž" * 200 + " ") * 3
    tex = tmp_path / "wrap.tex"
    tex.write_text(
        "\\documentclass{article}\\usepackage[T1]{fontenc}\\begin{document}\n"
        f"\\typeout{{{long_line}}}{long_line}\n\\end{{document}}\n",
        encoding="utf-8",
    )
    assert compile_pdf(tex).exists()
