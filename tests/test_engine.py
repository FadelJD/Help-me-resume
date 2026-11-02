"""build --compile picks the engine from the template; nobody runs latexmk by hand."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from cvforge import pipeline
from cvforge.compile import compile_tex, detect_engine
from cvforge.errors import CVForgeError

from .conftest import EXAMPLES, TEMPLATES
from .corpus import CORPUS, manifest, missing_requirements

DOC = "\\begin{document}x\\end{document}\n"


@pytest.mark.parametrize(
    ("preamble", "engines"),
    [
        ("\\documentclass{article}\n", ("pdflatex",)),
        ("%% engine: xelatex\n\\documentclass{article}\n", ("xelatex",)),
        ("\\documentclass{article}\\usepackage{fontspec}\n", ("xelatex", "lualatex")),
        ("\\documentclass{article}\\usepackage{luacode}\n", ("lualatex",)),
        (
            "\\documentclass{article}\\ifxetexorluatex\\usepackage{fontspec}\\fi\n",
            ("pdflatex", "lualatex", "xelatex"),
        ),
        ("\\documentclass{article}\n% \\usepackage{fontspec}\n", ("pdflatex",)),
    ],
)
def test_detect_engine_from_preamble(preamble: str, engines: tuple[str, ...]) -> None:
    assert detect_engine(preamble + DOC).engines == engines


def test_detect_engine_reads_local_class(tmp_path: Path) -> None:
    (tmp_path / "fancycv.cls").write_text("\\ClassError{fancycv}{LuaLaTeX is required}{}\n")
    text = "\\documentclass{fancycv}\n" + DOC
    assert detect_engine(text).engines == ("pdflatex",)
    assert detect_engine(text, [tmp_path]).engines == ("lualatex",)


@pytest.mark.tex
def test_build_compile_detects_pdflatex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = pipeline.build(
        profile=EXAMPLES / "profile.cv.txt",
        template=TEMPLATES / "minimal.tex",
        hat=None,
        job=None,
        output=tmp_path / "cv.tex",
        max_bullets=None,
        compile_pdf_too=True,
    )
    assert result.pdf is not None and result.pdf.exists()
    assert result.engine == "pdflatex" and "pdflatex" in result.summary


@pytest.mark.tex
def test_failure_is_one_line_naming_the_tex_line(tmp_path: Path) -> None:
    tex = tmp_path / "bad.tex"
    tex.write_text("\\documentclass{article}\n\\begin{document}\n\\nosuchmacro\n\\end{document}\n")
    with pytest.raises(CVForgeError) as exc:
        compile_tex(tex)
    (issue,) = exc.value.issues
    assert issue.line == 3 and "engines tried: pdflatex" in issue.message
    assert "\n" not in str(issue)


@pytest.mark.tex
@pytest.mark.corpus
@pytest.mark.parametrize("entry", manifest(), ids=[e["name"] for e in manifest()])
def test_corpus_compiles_without_an_engine_line(
    entry: dict[str, object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = missing_requirements(entry)  # type: ignore[arg-type]
    if missing:
        pytest.skip(f"needs {', '.join(missing)}; run tests/fixtures/templates/provision.sh")
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / str(entry["name"])
    shutil.copytree(CORPUS / str(entry["name"]), folder)
    template = folder / "template.tex"
    template.write_text(re.sub(r"^%% engine:.*\n", "", template.read_text(), flags=re.M))
    result = pipeline.build(
        profile=EXAMPLES / "profile.cv.txt",
        template=template,
        hat=None,
        job=None,
        output=folder / "out" / "cv.tex",
        max_bullets=None,
        compile_pdf_too=True,
    )
    assert result.pdf is not None and result.pdf.exists(), result.engine_note
