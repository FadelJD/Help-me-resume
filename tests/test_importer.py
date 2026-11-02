"""cvforge import: fictional data only (the user's real CVs never enter tests)."""

from __future__ import annotations

from pathlib import Path

import pytest

from cvforge import pipeline
from cvforge.importer import (
    Draft,
    DraftBullet,
    DraftItem,
    Src,
    confirm_markdown,
    import_file,
    mentions,
    merge,
    parse_date,
    split_dates,
    tex_to_text,
)
from cvforge.parse import load_profile

from .conftest import EXAMPLES

JAKES = Path(__file__).parent / "fixtures" / "templates" / "jakes-resume" / "template.tex"


@pytest.mark.parametrize(
    ("raw", "value"),
    [("Oct 2025", "2025-10"), ("Sept. 2021", "2021-09"), ("2021", "2021"), ("Present", "present")],
)
def test_parse_date(raw: str, value: str) -> None:
    assert parse_date(raw) == value


def test_split_dates() -> None:
    assert split_dates("May 2024 \u2013 Oct 2024") == ("2024-05", "2024-10")
    assert split_dates("2023") == ("2023", None)
    assert split_dates("Bangkok, TH") is None


def test_tex_to_text() -> None:
    links: list[str] = []
    text = tex_to_text("\\textbf{A \\& B} --- 50\\% \\href{https://x.example}{x.example}", links)
    assert text == "A & B \u2014 50% x.example" and links == ["https://x.example"]
    assert tex_to_text("one\ntwo \\\\ three") == "one two\nthree"


def test_mentions_is_whole_term() -> None:
    assert mentions("SQL-based checks", "SQL") and not mentions("GitLab repo", "Git")
    assert mentions("ships .NET Core apps", ".NET Core")


@pytest.fixture
def built(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    result = pipeline.build(
        profile=EXAMPLES / "profile.cv.txt",
        template=JAKES,
        hat=None,
        job=None,
        output=tmp_path / "out" / "cv.tex",
        max_bullets=None,
        compile_pdf_too=True,
    )
    assert result.pdf is not None
    return result.tex


def _facts(path: Path) -> tuple[list[tuple[str, str, str]], list[str]]:
    p = load_profile(path).profile
    roles = [(e.title, e.org, f"{e.start}..{e.end}") for e in p.experience]
    bullets = [b.text for i in p.all_items() for b in i.bullets]
    return roles, bullets


@pytest.mark.tex
@pytest.mark.parametrize("kind", ["tex", "pdf"])
def test_import_reproduces_the_source_profile(built: Path, kind: str, tmp_path: Path) -> None:
    source = built if kind == "tex" else built.with_suffix(".pdf")
    out = tmp_path / f"{kind}.cv.txt"
    result = pipeline.import_profiles([source], out, None, force=False)
    assert not [i for i in result.issues if i.severity == "error"], result.issues
    roles, bullets = _facts(out)
    want_roles, want_bullets = _facts(EXAMPLES / "profile.cv.txt")
    assert roles == want_roles
    if kind == "pdf":  # Jake's OT1 encoding draws underscores as rules: the PDF lost them
        want_bullets = [b.replace("_", " ") for b in want_bullets]
    assert sorted(bullets) == sorted(want_bullets)
    text = out.read_text()
    assert "# source:" in text and "weight: 3  # default" in text


def _draft(label: str, title: str, date: str, bullets: list[str]) -> Draft:
    item = DraftItem(
        section="experience",
        title=Src(title, [f"{label} p.1"]),
        org=Src("Example Org", [f"{label} p.1"]),
        start=Src(date, [f"{label} p.1"]),
        end=Src("present", [f"{label} p.1"]),
        bullets=[DraftBullet(Src(b, [f"{label} p.1"])) for b in bullets],
    )
    return Draft(label=label, name=Src("Pat Example", [f"{label} p.1"]), items=[item])


def test_merge_unions_dedupes_and_flags_disagreements() -> None:
    a = _draft("cv-x", "Writer", "2024-01", ["Wrote the API guide.", "Ran the docs build."])
    b = _draft(
        "cv-y",
        "Writer",
        "2024-02",
        ["Wrote the API guide", "Ran the documentation build.", "Hired two editors."],
    )
    merged = merge([a, b])
    item = merged.draft.items[0]
    texts = [x.text.value for x in item.bullets]
    assert texts == ["Wrote the API guide.", "Ran the docs build.", "Hired two editors."]
    assert item.bullets[0].text.sources == ["cv-x p.1", "cv-y p.1"]  # same text, both sources
    whats = [c.what for c in merged.confirms]
    assert any("start date" in w for w in whats)
    assert any("two wordings" in w for w in whats)
    assert item.start is not None and item.start.value == "2024-01" and item.start.confirm
    md = confirm_markdown(merged, ["cv-x", "cv-y"])
    assert "Ran the documentation build." in md and "(in the profile now)" in md


def test_import_refuses_to_overwrite(tmp_path: Path) -> None:
    out = tmp_path / "p.cv.txt"
    out.write_text("x")
    with pytest.raises(Exception, match="already exists"):
        pipeline.import_profiles([EXAMPLES / "profile.cv.txt"], out, None, force=False)


def test_import_rejects_other_formats(tmp_path: Path) -> None:
    f = tmp_path / "cv.docx"
    f.write_text("x")
    with pytest.raises(Exception, match=r"\.pdf or \.tex"):
        import_file(f)
