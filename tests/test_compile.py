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


@pytest.mark.tex
def test_direct_engine_runs_resolve_references(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without latexmk, compile runs the engine twice (a third time if the .aux changed).
    monkeypatch.setenv("CVFORGE_NO_LATEXMK", "1")
    tex = tmp_path / "ref.tex"
    tex.write_text(
        "\\documentclass{article}\\begin{document}\n"
        "See section~\\ref{s}.\\section{Target}\\label{s}\n\\end{document}\n"
    )
    assert compile_pdf(tex).exists()
    log = tex.with_suffix(".log").read_text(encoding="utf-8", errors="replace")
    assert "undefined references" not in log and "Rerun to get" not in log


@pytest.mark.tex
def test_direct_engine_third_pass_when_aux_keeps_changing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess

    calls: list[list[str]] = []
    real = subprocess.run

    def spy(cmd: list[str], **kw: object) -> object:
        calls.append(cmd)
        return real(cmd, **kw)  # type: ignore[call-overload]

    monkeypatch.setenv("CVFORGE_NO_LATEXMK", "1")
    monkeypatch.setattr(subprocess, "run", spy)
    tex = tmp_path / "grow.tex"
    # Writes the run count into the .aux, so the .aux differs after pass 1 and pass 2.
    tex.write_text(
        "\\documentclass{article}\\makeatletter\n"
        "\\newcount\\runs\\AtBeginDocument{\\@ifundefined{prevruns}{\\runs=0}"
        "{\\runs=\\prevruns}\\global\\advance\\runs by 1}\n"
        "\\AtEndDocument{\\immediate\\write\\@auxout{\\gdef\\string\\prevruns{\\the\\runs}}}\n"
        "\\makeatother\\begin{document}x\\end{document}\n"
    )
    compile_pdf(tex)
    assert len([c for c in calls if c[0] == "pdflatex"]) == 3


def test_missing_engine_says_run_doctor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CVFORGE_NO_LATEXMK", "1")
    monkeypatch.setenv("PATH", str(tmp_path))  # nothing on PATH
    tex = tmp_path / "x.tex"
    tex.write_text("\\documentclass{article}\\begin{document}x\\end{document}\n")
    with pytest.raises(CVForgeError) as exc:
        compile_pdf(tex)
    issue = exc.value.issues[0]
    assert "pdflatex is not on PATH" in issue.message and "cvforge doctor" in issue.fix


def test_parse_log_error_unwraps_long_lines() -> None:
    path = "/" + "d" * 70 + "/bad.tex"
    wrapped = path + ":3: Undefined control sequence."
    log = "\n".join(wrapped[i : i + 79] for i in range(0, len(wrapped), 79)) + "\nl.3 \\x\n"
    assert parse_log_error(log) == (3, "Undefined control sequence.")
