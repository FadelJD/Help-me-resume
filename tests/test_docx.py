"""build --docx: the Word copy holds every fact `check` looks for in the PDF, in one column."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from docx import Document
from typer.testing import CliRunner

from cvforge import pipeline
from cvforge.check import expected_facts, extracted_variants, judge
from cvforge.cli import app
from cvforge.config import LOCALES
from cvforge.docx_export import date_range
from cvforge.pipeline import BuildResult

from .conftest import EXAMPLES, TEMPLATES

runner = CliRunner()
HAT = EXAMPLES / "hats" / "developer.toml"
HEADINGS = ["Experience", "Projects", "Skills", "Education"]  # the developer hat's order


@pytest.fixture(autouse=True)
def _cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def _build(tmp_path: Path, max_bullets: int | None = None, docx: bool = True) -> BuildResult:
    return pipeline.build(
        profile=EXAMPLES / "profile.cv.txt",
        template=TEMPLATES / "minimal.tex",
        hat=str(HAT),
        job=None,
        output=tmp_path / "out" / "cv.tex",
        max_bullets=max_bullets,
        compile_pdf_too=False,
        docx=docx,
    )


def _text(path: Path) -> str:
    return "\n".join(p.text for p in Document(str(path)).paragraphs)


def test_docx_holds_every_fact_check_expects(tmp_path: Path) -> None:
    result = _build(tmp_path)
    assert result.docx == tmp_path / "out" / "cv.docx" and result.docx.exists()
    variants = extracted_variants(_text(result.docx))
    facts = expected_facts(result.report)
    assert len(facts) > 20
    verdicts = {
        (f.item, f.field): judge(variants, f.expected, prefix=f.field == "bullet") for f in facts
    }
    assert {k: v for k, v in verdicts.items() if v != "intact"} == {}


def test_docx_layout_is_one_column_of_plain_paragraphs(tmp_path: Path) -> None:
    result = _build(tmp_path)
    assert result.docx is not None
    doc = Document(str(result.docx))
    assert not doc.tables and not doc.inline_shapes
    headings = [
        p.text for p in doc.paragraphs if p.style is not None and p.style.name == "Heading 1"
    ]
    assert headings == HEADINGS
    with zipfile.ZipFile(result.docx) as z:
        names = z.namelist()
        body = z.read("word/document.xml").decode("utf-8")
    for tag in ("<w:tbl>", "<w:txbxContent", "<w:drawing", "<v:textbox", "<w:pict"):
        assert tag not in body, tag
    assert not [n for n in names if n.startswith(("word/header", "word/footer", "word/media"))]
    for section in doc.sections:
        assert not section.header.paragraphs or not any(p.text for p in section.header.paragraphs)
        assert not any(p.text for p in section.footer.paragraphs)
    styles = {p.style.name for p in doc.paragraphs if p.style is not None}
    assert styles <= {"Title", "Normal", "Heading 1", "List Bullet"}


def test_docx_follows_the_tex_selection_and_dates(tmp_path: Path) -> None:
    result = _build(tmp_path, max_bullets=2)
    assert result.docx is not None
    doc = Document(str(result.docx))
    bullets = [
        p.text for p in doc.paragraphs if p.style is not None and p.style.name == "List Bullet"
    ]
    emitted = [b["text"] for item in result.report["emitted"]["items"] for b in item["bullets"]]
    assert bullets == emitted  # same bullets, same order, same per-role limit
    roles = [i for i in result.report["emitted"]["items"] if i["section"] == "experience"]
    text = _text(result.docx)
    for role in roles:
        assert f"{role['title']}, {role['org']}" in text
        assert f"{role['start']} to {role['end']}" in text
    assert "Jun 2025 to Present" in text  # the locale's month format, as in the .tex


def test_date_range() -> None:
    th = LOCALES["th"]
    assert date_range("2023-06", "present", th) == "Jun 2023 to Present"
    assert date_range(None, "2021-05", th) == "May 2021"
    assert date_range("2019", "2021", th) == "2019 to 2021"


def test_build_json_lists_the_docx() -> None:
    common = ["-p", str(EXAMPLES / "profile.cv.txt"), "--hat", str(HAT)]
    common += ["-t", str(TEMPLATES / "minimal.tex"), "-o", "out/x.tex", "--json"]
    r = runner.invoke(app, ["build", *common, "--docx"])
    assert r.exit_code == 0, r.stdout + r.stderr
    data = json.loads(r.stdout)
    assert data["docx"] == "out/x.docx" and Path("out/x.docx").exists()
    r = runner.invoke(app, ["build", *common[:-1]])
    assert r.exit_code == 0 and "docx" not in r.stdout


def test_build_without_docx_writes_none(tmp_path: Path) -> None:
    result = _build(tmp_path, docx=False)
    assert result.docx is None
    assert not list((tmp_path / "out").glob("*.docx"))
    r = runner.invoke(
        app,
        [
            "build",
            "-p",
            str(EXAMPLES / "profile.cv.txt"),
            "-t",
            str(TEMPLATES / "minimal.tex"),
            "-o",
            "other/y.tex",
            "--json",
        ],
    )
    assert r.exit_code == 0 and json.loads(r.stdout)["docx"] is None
    assert not list(Path("other").glob("*.docx"))
