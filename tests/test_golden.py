"""Golden files: every corpus template x every person, rendered .tex committed under tests/golden.

A mismatch fails with the diff. To accept an intended change run
`pytest tests/test_golden.py --update-goldens` and explain why in the commit message.
"""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest

from cvforge import pipeline

from .conftest import EXAMPLES, ROOT

GOLDEN = ROOT / "tests" / "golden"
CORPUS = ROOT / "tests" / "fixtures" / "templates"
TEMPLATE_NAMES = ["jakes-resume", "altacv", "moderncv", "awesome-cv", "deedy-resume"]
PEOPLE: dict[str, tuple[Path, Path]] = {
    "sample": (EXAMPLES / "profile.cv.txt", EXAMPLES / "hats" / "full-stack-engineer.toml"),
    **{
        p.name: (p / "profile.cv.txt", p / "hat.toml")
        for p in sorted((EXAMPLES / "people").iterdir())
        if (p / "profile.cv.txt").exists()
    },
}
CASES = [(t, person) for t in TEMPLATE_NAMES for person in PEOPLE]


def test_golden_matrix_is_complete() -> None:
    assert len(PEOPLE) == 5 and len(CASES) == 25


@pytest.mark.parametrize(("template", "person"), CASES, ids=[f"{t}-{p}" for t, p in CASES])
def test_golden(
    template: str,
    person: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    monkeypatch.chdir(tmp_path)  # no cvforge.toml from the caller's folder
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1793404800")  # 2026-11-01, fixed build date
    profile, hat = PEOPLE[person]
    result = pipeline.build(
        profile=profile,
        template=CORPUS / template / "template.tex",
        hat=str(hat),
        job=None,
        output=tmp_path / "cv.tex",
        max_bullets=None,
        compile_pdf_too=False,
    )
    rendered = result.tex.read_text(encoding="utf-8")
    golden = GOLDEN / template / f"{person}.tex"
    if request.config.getoption("--update-goldens"):
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(rendered, encoding="utf-8")
        return
    assert golden.exists(), f"missing {golden}; run pytest {__file__} --update-goldens"
    expected = golden.read_text(encoding="utf-8")
    if rendered != expected:
        diff = "".join(
            difflib.unified_diff(
                expected.splitlines(keepends=True),
                rendered.splitlines(keepends=True),
                fromfile=str(golden.relative_to(ROOT)),
                tofile="rendered now",
            )
        )
        pytest.fail(f"golden mismatch for {template} x {person}:\n{diff}")


@pytest.mark.tex
@pytest.mark.corpus
@pytest.mark.parametrize(("template", "person"), CASES, ids=[f"{t}-{p}" for t, p in CASES])
def test_golden_compiles(template: str, person: str, tmp_path: Path) -> None:
    from cvforge.compile import compile_pdf
    from cvforge.template import parse_header

    from .corpus import manifest, missing_requirements

    entry = next(e for e in manifest() if e["name"] == template)
    missing = missing_requirements(entry)
    if missing:
        pytest.skip(f"needs {', '.join(missing)}; run tests/fixtures/templates/provision.sh")
    tex = tmp_path / "cv.tex"
    tex.write_text((GOLDEN / template / f"{person}.tex").read_text(encoding="utf-8"))
    header, _ = parse_header(tex.read_text(encoding="utf-8"), str(tex))
    assert header is not None
    assert compile_pdf(tex, engine=header.engine, search=[CORPUS / template]).exists()
