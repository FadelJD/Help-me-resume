from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest

from cvforge import pipeline
from cvforge.errors import CVForgeError, errors_only
from cvforge.interview import run_interview, skill_id
from cvforge.parse import load_hat, load_profile
from cvforge.validate import validate_profile


def _scripted(answers: list[str], confirms: list[bool]) -> tuple[object, object, object]:
    a: Iterator[str] = iter(answers)
    c: Iterator[bool] = iter(confirms)
    said: list[str] = []
    return (lambda _p, _d: next(a)), (lambda _p, _d: next(c)), said.append


def test_skill_id() -> None:
    assert skill_id(".NET / C#", set()) == "net-c"
    assert skill_id("Python", {"python"}) == "python-2"


def test_interview_full_flow() -> None:
    ask, confirm, say = _scripted(
        [
            "Sam Lee",
            "sam@example.com",
            "",
            "Bangkok, TH",
            "github.com/sam",
            "Python, Docker",
            "Developer",
            "Example Co",
            "2023-13",
            "2023-01",
            "present",
            "Built an API in Python.",
            "python, FastAPI",
            "4",
            "B.Sc.",
            "Example University",
            "2022-05",
            "",
            "developer",
            "th",
        ],
        [True, True, False, False, True, False],
    )
    result = run_interview(ask, confirm, say, today=date(2026, 11, 1))  # type: ignore[arg-type]
    p = result.profile
    assert p.person.phone is None
    assert p.skills == {"python": "Python", "docker": "Docker", "fastapi": "FastAPI"}
    assert p.experience[0].start == "2023-01"  # re-asked after the invalid 2023-13
    assert p.experience[0].bullets[0].skills == ["python", "fastapi"]
    assert p.education[0].end == "2022-05"


def test_init_with_all_defaults_validates(tmp_path: Path) -> None:
    result = pipeline.init(
        lambda _p, d: d, lambda _p, _d: False, lambda _m: None, directory=tmp_path
    )
    parsed = load_profile(result.path)
    assert errors_only(validate_profile(parsed)) == []
    assert (tmp_path / "cvforge.toml").exists()
    assert (
        load_hat(tmp_path / "hats" / "full-stack-engineer.toml").title_line == "Full-Stack Engineer"
    )


def test_init_refuses_to_overwrite(tmp_path: Path) -> None:
    (tmp_path / "profile.cv.txt").write_text("x")
    with pytest.raises(CVForgeError):
        pipeline.init(lambda _p, d: d, lambda _p, _d: False, lambda _m: None, directory=tmp_path)


@pytest.fixture
def fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    pipeline.init(lambda _p, d: d, lambda _p, _d: False, lambda _m: None, directory=tmp_path)
    return tmp_path


def test_add_commands_round_trip(fresh: Path) -> None:
    pipeline.add_skill(None, "rust", "Rust")
    pipeline.add_role(
        None,
        title="Dev",
        org="Acme",
        start="2024-01",
        end="present",
        location=None,
        tags=[],
        item_id=None,
    )
    pipeline.add_bullet(
        None, item_id="exp-01", text_="Cut latency 30%.", skills=["rust"], weight=4, bullet_id=None
    )
    pipeline.add_project(None, name="Tool", url="example.dev", item_id=None)
    pipeline.add_education(None, degree="B.Sc.", org="Uni", start=None, end="2020-05", item_id=None)
    p = load_profile(fresh / "profile.cv.txt").profile
    assert p.experience[0].bullets[0].id == "b1"
    assert p.projects[0].id == "prj-01"
    assert p.education[0].id == "edu-01"


def test_add_bullet_with_unknown_skill_writes_nothing(fresh: Path) -> None:
    pipeline.add_role(
        None,
        title="Dev",
        org="Acme",
        start="2024-01",
        end="present",
        location=None,
        tags=[],
        item_id=None,
    )
    before = (fresh / "profile.cv.txt").read_text()
    with pytest.raises(CVForgeError) as exc:
        pipeline.add_bullet(
            None, item_id="exp-01", text_="x", skills=["nope"], weight=3, bullet_id=None
        )
    assert exc.value.issues[0].line is None
    assert (fresh / "profile.cv.txt").read_text() == before


def test_add_role_bad_date(fresh: Path) -> None:
    with pytest.raises(CVForgeError) as exc:
        pipeline.add_role(
            None,
            title="Dev",
            org="Acme",
            start="Jan 2024",
            end="present",
            location=None,
            tags=[],
            item_id=None,
        )
    assert "YYYY-MM" in exc.value.issues[0].fix


def test_init_then_build(fresh: Path) -> None:
    from .conftest import TEMPLATES

    pipeline.add_skill(None, "py", "Python")
    pipeline.add_role(
        None,
        title="Dev",
        org="Acme",
        start="2024-01",
        end="present",
        location=None,
        tags=[],
        item_id=None,
    )
    pipeline.add_bullet(
        None, item_id="exp-01", text_="Shipped a tool.", skills=["py"], weight=3, bullet_id=None
    )
    result = pipeline.build(
        profile=None,
        template=TEMPLATES / "minimal.tex",
        hat=None,
        job=None,
        output=None,
        max_bullets=None,
        compile_pdf_too=False,
    )
    assert "% id:exp-01.b1" in result.tex.read_text()


def test_init_example_writes_a_working_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = pipeline.init(
        lambda _p, d: d, lambda _p, _d: False, lambda _m: None, directory=tmp_path, example=True
    )
    assert load_profile(result.path).profile.person.name == "Jane Doe"
    assert (tmp_path / "hats" / "developer.toml").exists()
    built = pipeline.build(
        profile=None,
        template=None,
        hat=None,
        job=None,
        output=tmp_path / "out" / "cv.tex",
        max_bullets=None,
        compile_pdf_too=False,
    )
    assert "Software Developer" in built.tex.read_text()  # template minimal, hat developer


def test_builtin_template_names() -> None:
    from cvforge.config import Config
    from cvforge.resources import builtin_template, builtin_templates

    assert {"minimal", "minimal-right-dates"} <= set(builtin_templates())
    assert builtin_template("minimal") is not None
    assert builtin_template("nope") is None and builtin_template("x/minimal.tex") is None
    assert pipeline.resolve_template(Path("minimal"), Config()).name == "minimal.tex"
