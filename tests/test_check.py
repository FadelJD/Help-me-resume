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
    found_instead,
    garbled_count,
    miss_issues,
    normalize,
    resolve_parsers,
)
from cvforge.config import ParserSetting, Thresholds
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
    misses = {(p.name, m.fact.item, m.fact.expected) for p in result.parsers for m in p.misses}
    assert ("pypdf-layout", "person", "jane@example.com") in misses
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
    default_gate = True
    about = "test double"

    def unavailable(self) -> str | None:
        return "not installed"

    def extract(self, pdf: Path) -> str:  # pragma: no cover
        raise AssertionError


@pytest.mark.tex
def test_unavailable_parser_is_skipped_not_failed(workdir: Path) -> None:
    from cvforge.parsers.pdftotext import PdfToText

    tex = _build(TEMPLATES / "minimal.tex", workdir / "out" / "p.tex")
    result = check(
        tex,
        None,
        Thresholds(),
        semantic=False,
        parsers=[PdfToText(), _Missing()],  # type: ignore[list-item]
    )
    assert result.ok
    assert any("imaginary" in w.message for w in result.warnings)


def test_found_instead_shows_garbled_span() -> None:
    text = "Experience T echnical W riter | Acme Software"
    assert found_instead(text, "Technical Writer") == "T echnical W riter"
    assert found_instead("Bjane@example.com H+66", "jane@example.com") == "Bjane@example.com"
    assert found_instead("nothing like it", "Kubernetes Operator") is None


def test_resolve_parsers_defaults_and_overrides() -> None:
    gates = {p.name: g for p, g in resolve_parsers({})}
    assert gates == {
        "pdftotext": True,
        "pdftotext-layout": False,
        "pdfplumber": True,
        "pypdf-layout": True,
        "pypdf": False,
    }
    over = {
        "pypdf": ParserSetting(gate=True),
        "pdftotext-layout": ParserSetting(enabled=False),
    }
    gates = {p.name: g for p, g in resolve_parsers(over)}
    assert gates["pypdf"] is True and "pdftotext-layout" not in gates


def test_unknown_parser_in_config() -> None:
    with pytest.raises(CVForgeError) as exc:
        resolve_parsers({"pdfminer": ParserSetting()})
    assert "pdftotext" in exc.value.issues[0].fix


@pytest.mark.tex
def test_pypdf_default_is_advisory_and_shows_what_it_read(workdir: Path) -> None:
    tex = _build(TEMPLATES / "minimal.tex", workdir / "out" / "adv.tex")
    result = check(tex, None, Thresholds(), semantic=False)
    plain = next(p for p in result.parsers if p.name == "pypdf")
    assert plain.gate is False
    assert result.roundtrip_ok  # advisory misses never fail check
    found = {m.found for m in plain.misses}
    assert any(f and "T echnical W riter" in f for f in found)
    issues = [i for i in miss_issues(result) if "advisory" in i.message]
    assert issues and all(i.severity == "warning" for i in issues)


@pytest.mark.tex
def test_gating_config_can_make_pypdf_fail_check(workdir: Path) -> None:
    tex = _build(TEMPLATES / "minimal.tex", workdir / "out" / "g.tex")
    result = check(
        tex, None, Thresholds(), semantic=False, settings={"pypdf": ParserSetting(gate=True)}
    )
    assert not result.roundtrip_ok


class _FakeEncoder:
    def encode(self, sentences: list[str], normalize_embeddings: bool = True) -> list[list[float]]:
        return [[1.0, 0.0] if "Node.js" in s else [0.6, 0.8] for s in sentences]


@pytest.mark.tex
def test_semantic_score_path_with_fake_encoder(workdir: Path) -> None:
    tex = _build(TEMPLATES / "minimal.tex", workdir / "out" / "sem.tex")
    job = (FIXTURES / "job_backend.txt").read_text()
    result = check(tex, job, Thresholds(), encoder=_FakeEncoder())
    assert result.scores["semantic"] == 1.0  # both texts mention Node.js
    assert "semantic: 1.00" in result.badge


@pytest.mark.tex
def test_semantic_unavailable_says_why_and_how(
    workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    real_import = builtins.__import__

    def no_st(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("sentence_transformers"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", no_st)
    tex = _build(TEMPLATES / "minimal.tex", workdir / "out" / "nosem.tex")
    result = check(tex, "Node.js developer", Thresholds())
    assert result.scores["semantic"] is None
    assert "not installed" in result.scores["semantic_unavailable"]
    assert "cvforge[semantic]" in result.scores["semantic_fix"]
    assert "SentenceTransformer(" in result.scores["semantic_fix"]


class _Scrambled:
    """Returns every fact, but dates on their own line above the title, as pdftotext did."""

    name = "scrambled"
    default_gate = True
    about = "test double"

    def unavailable(self) -> str | None:
        return None

    def extract(self, pdf: Path) -> str:
        dash = chr(0x2013)
        return (
            f"Jun 2025 {dash} Present\n\nSkills\nWriter\nAcme\nJane\n"
            "one two three four five six seven eight"
        )


def test_roundtrip_is_order_independent() -> None:
    from cvforge.check import Fact, roundtrip

    facts = [
        Fact("exp-01", "title", "Writer"),
        Fact("exp-01", "start", "Jun 2025"),
        Fact("exp-01", "end", "Present"),
        Fact("exp-01.b1", "bullet", "one two three four five six seven eight"),
    ]
    result, _ = roundtrip(_Scrambled(), Path("unused.pdf"), facts, gate=True)
    assert result.ok


@pytest.mark.tex
def test_right_aligned_dates_pass_every_gating_parser(workdir: Path) -> None:
    tex = _build(TEMPLATES / "minimal-right-dates.tex", workdir / "out" / "right.tex")
    result = check(tex, None, Thresholds(), semantic=False)
    assert result.roundtrip_ok, [(p.name, p.misses) for p in result.gating]


# Tolerance rules derived from the template corpus (docs/parser-table.md, DECISIONS.md).


def test_rule_case_is_styling_not_loss() -> None:
    from cvforge.check import judge

    # AltaCV and Deedy upper-case names and employers in every parser.
    assert judge(["JANE DOE | ACME SOFTWARE"], "Jane Doe") == "intact"
    assert judge(["JANE DOE | ACME SOFTWARE"], "Acme Software") == "intact"


def test_rule_soft_hyphen_is_a_hyphen() -> None:
    from cvforge.check import judge

    # LuaLaTeX output (Awesome-CV) maps the visible hyphen to U+00AD.
    assert judge(extracted_variants("Owned end­to­end docs"), "end-to-end") == "intact"


def test_rule_glued_words_are_a_warning_not_a_loss() -> None:
    from cvforge.check import contains_glued, judge

    # pdfplumber and pypdf drop inter-word spaces on tight fonts (AltaCV, Awesome-CV, Deedy).
    assert judge(["AcmeSoftware | Bangkok"], "Acme Software") == "glued"
    assert judge(
        ["• BuiltaPythonpipelinemigrating400articlesto"], "Built a Python", prefix=True
    ) == ("glued")
    # ...but icon junk glued on, a neighbouring word, or spaces inside words still fail.
    assert not contains_glued("Bjane@example.com", "jane example")
    assert not contains_glued("2025Jun2025-Present", "Jun 2025")
    assert not contains_glued("T echnical W riter", "Technical Writer")
    assert judge(["�+66800000000"], "+66 80 000 0000") == "missing"


def test_rule_interleaved_columns_are_named() -> None:
    from cvforge.check import judge

    # Two-column templates (AltaCV, Deedy) split a phrase around the other column's text.
    text = "B.Eng. Computer Innovation Jun 2025 - Present Engineering KMITL"
    assert judge([text], "B.Eng. Computer Innovation Engineering") == "interleaved"


def test_dates_separated_counts_roles() -> None:
    from cvforge.check import dates_separated

    items = [
        {"section": "experience", "title": "Writer", "start": "Jun 2025"},
        {"section": "experience", "title": "Developer", "start": "Jan 2024"},
    ]
    raw = "Jun 2025 - Present\nJan 2024\nx\ny\nWriter\nDeveloper Jan 2024"
    assert dates_separated(raw, items) == (1, 2)
