from __future__ import annotations

import json
from pathlib import Path

import pytest

from cvforge import pipeline
from cvforge.check import (
    check,
    contains_word,
    expected_facts,
    extracted_variants,
    garbled_count,
    normalize,
)
from cvforge.config import Thresholds
from cvforge.errors import CVForgeError

from .conftest import EXAMPLES, FIXTURES, TEMPLATES


def test_contains_word_rejects_glued_text() -> None:
    assert contains_word("Email: jane@example.com |", "jane@example.com")
    assert not contains_word("Bjane@example.com", "jane@example.com")
    assert not contains_word("�Acme Software", "Acme Software")
    assert not contains_word("PythonZTypeScript", "TypeScript")
    assert contains_word("Python, TypeScript", "TypeScript")
    assert contains_word("C# code", "C#")


def test_normalize_maps_ligatures_dashes_and_cid() -> None:
    raw = f"\ufb01le {chr(0x2013)} {chr(0x2019)}s"
    assert normalize(raw) == "file - 's"
    assert normalize("(cid:66)x") == "�x"
    assert normalize("2--3") == "2-3"


def test_hyphenation_variants() -> None:
    joined, kept = extracted_variants("documen-\ntation end-to-\nend")
    assert "documentation" in joined
    assert "end-to-end" in kept


def test_garbled_count() -> None:
    assert garbled_count("(cid:66)ab\n") == 2


def _report(fields: list[str]) -> dict[str, object]:
    return {
        "template_fields": fields,
        "emitted": {
            "person": {"name": "Jane", "email": "j@x.io", "phone": ""},
            "items": [
                {
                    "id": "exp-01",
                    "section": "experience",
                    "title": "Writer",
                    "org": "Acme",
                    "start": "Jun 2025",
                    "end": "Present",
                    "bullets": [
                        {"id": "exp-01.b1", "text": "one two three four five six seven eight nine"}
                    ],
                }
            ],
            "skills": ["Python"],
        },
    }


def test_expected_facts_follow_template_fields() -> None:
    facts = expected_facts(_report(["person.name", "experience.title", "skills"]))
    kinds = {(f.item, f.field) for f in facts}
    assert ("person", "name") in kinds and ("person", "email") not in kinds
    assert ("exp-01", "title") in kinds and ("exp-01", "org") not in kinds
    bullet = next(f for f in facts if f.field == "bullet")
    assert bullet.expected == "one two three four five six seven eight"
    assert ("skills", "skill") in kinds


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _build(template: Path, out: Path) -> Path:
    return pipeline.build(
        profile=EXAMPLES / "profile.cv.txt",
        template=template,
        hat=str(EXAMPLES / "hats" / "developer.toml"),
        job=None,
        output=out,
        max_bullets=None,
        compile_pdf_too=False,
    ).tex


def test_check_needs_report(workdir: Path) -> None:
    tex = workdir / "lonely.tex"
    tex.write_text("x")
    with pytest.raises(CVForgeError) as exc:
        check(tex, None, Thresholds())
    assert "report.json" in exc.value.issues[0].message


@pytest.mark.tex
def test_roundtrip_passes_on_minimal(workdir: Path) -> None:
    tex = _build(TEMPLATES / "minimal.tex", workdir / "out" / "min.tex")
    job = (FIXTURES / "job_backend.txt").read_text()
    result = check(tex, job, Thresholds(), semantic=False)
    assert result.roundtrip_ok, [(p.name, p.misses) for p in result.parsers]
    assert all(p.skipped is None for p in result.parsers)
    assert result.scores["evidence"] == 1.0
    assert 0 < result.scores["keyword"] <= 1
    saved = json.loads(tex.with_suffix(".report.json").read_text())
    assert saved["check"]["roundtrip_ok"] is True


@pytest.mark.tex
def test_roundtrip_fails_on_icon_template_naming_the_string(workdir: Path) -> None:
    tex = _build(FIXTURES / "template_icons.tex", workdir / "out" / "icons.tex")
    result = check(tex, None, Thresholds(), semantic=False)
    assert not result.ok
    misses = {(p.name, m.item, m.expected) for p in result.parsers for m in p.misses}
    assert ("pypdf", "person", "jane@example.com") in misses
    assert any(name == "pdfplumber" and item == "exp-01" for name, item, _ in misses)


@pytest.mark.tex
def test_twocol_template_warns_in_lint(workdir: Path) -> None:
    tex = _build(FIXTURES / "template_twocol.tex", workdir / "out" / "two.tex")
    result = check(tex, None, Thresholds(), semantic=False, lint_template=True)
    assert any("two-column" in i.message for i in result.lint)


@pytest.mark.tex
def test_strict_uses_thresholds(workdir: Path) -> None:
    tex = _build(TEMPLATES / "minimal.tex", workdir / "out" / "s.tex")
    job = (FIXTURES / "job_backend.txt").read_text()
    loose = check(tex, job, Thresholds(keyword=0.99), semantic=False)
    assert loose.ok  # report-only by default
    strict = check(tex, job, Thresholds(keyword=0.99), semantic=False, strict=True)
    assert not strict.ok and "keyword" in strict.strict_failures[0]


class _Missing:
    name = "imaginary"

    def unavailable(self) -> str | None:
        return "not installed"

    def extract(self, pdf: Path) -> str:  # pragma: no cover
        raise AssertionError


@pytest.mark.tex
def test_unavailable_parser_is_skipped_not_failed(workdir: Path) -> None:
    from cvforge.parsers.pdftotext import PdfToText

    tex = _build(TEMPLATES / "minimal.tex", workdir / "out" / "p.tex")
    result = check(tex, None, Thresholds(), semantic=False, parsers=[PdfToText(), _Missing()])
    assert result.ok
    assert any("imaginary" in w.message for w in result.warnings)
