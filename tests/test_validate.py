from __future__ import annotations

import pytest

from cvforge.errors import errors_only
from cvforge.parse import load_hat, load_profile
from cvforge.schema import Hat
from cvforge.validate import validate_hat, validate_profile

from .conftest import EXAMPLES, FIXTURES


def test_sample_profile_is_clean() -> None:
    assert validate_profile(load_profile(EXAMPLES / "profile.cv.txt")) == []


def test_fixture_ok_is_clean() -> None:
    assert errors_only(validate_profile(load_profile(FIXTURES / "profile_ok.cv.txt"))) == []


@pytest.mark.parametrize(
    ("fixture", "needle", "line", "item"),
    [
        ("profile_bad_skill_ref.cv.txt", "pyhton", 20, "exp-01.b2"),
        ("profile_bad_duplicate_id.cv.txt", "used twice", 21, "exp-01"),
        ("profile_bad_duplicate_bullet.cv.txt", "used twice", 18, "exp-01.b1"),
        ("profile_bad_date_order.cv.txt", "before start", 12, "exp-01"),
    ],
)
def test_bad_fixture(fixture: str, needle: str, line: int, item: str) -> None:
    errs = errors_only(validate_profile(load_profile(FIXTURES / fixture)))
    assert len(errs) == 1
    assert needle in errs[0].message
    assert errs[0].line == line
    assert errs[0].item == item
    assert errs[0].fix


def test_typo_gets_a_suggestion() -> None:
    errs = errors_only(validate_profile(load_profile(FIXTURES / "profile_bad_skill_ref.cv.txt")))
    assert "Did you mean `py`" in errs[0].fix


def test_unevidenced_skill_is_a_warning() -> None:
    issues = validate_profile(load_profile(FIXTURES / "profile_bad_skill_ref.cv.txt"))
    warnings = [i for i in issues if i.severity == "warning"]
    assert warnings and warnings[0].item == "py"


@pytest.mark.parametrize("hat", ["developer", "full-stack-engineer", "technical-writer"])
def test_example_hats_match_example_profile(hat: str) -> None:
    profile = load_profile(EXAMPLES / "profile.cv.txt").profile
    path = EXAMPLES / "hats" / f"{hat}.toml"
    assert validate_hat(load_hat(path), profile, str(path)) == []


def test_hat_unknown_skill() -> None:
    profile = load_profile(EXAMPLES / "profile.cv.txt").profile
    issues = validate_hat(Hat(name="x", skill_weights={"pyton": 1.0}), profile, "h.toml")
    assert "Did you mean `py`" in issues[0].fix
