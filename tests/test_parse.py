from __future__ import annotations

from pathlib import Path

import pytest

from cvforge.errors import CVForgeError
from cvforge.parse import (
    append_bullet,
    append_item,
    append_skill,
    dump_profile,
    load_hat,
    load_profile,
    next_id,
    parse_text,
)
from cvforge.schema import Bullet, Experience

from .conftest import EXAMPLES, FIXTURES


def test_sample_profile_parses() -> None:
    parsed = load_profile(EXAMPLES / "profile.cv.txt")
    p = parsed.profile
    assert p.person.name == "Jane Doe"
    assert p.experience[0].bullets[1].text.startswith("Built a Python pipeline")
    assert p.experience[0].start == "2025-06"
    assert parsed.source.line(("experience", 0, "bullets", 1, "text")) is not None


def test_unknown_key_names_line_and_allowed_keys() -> None:
    with pytest.raises(CVForgeError) as exc:
        load_profile(FIXTURES / "profile_bad_unknown_key.cv.txt")
    unknown = [i for i in exc.value.issues if "titel" in i.message]
    assert unknown and unknown[0].line == 9
    assert unknown[0].item == "exp-01"
    assert "title" in unknown[0].fix


def test_bad_date_names_line_and_format() -> None:
    with pytest.raises(CVForgeError) as exc:
        load_profile(FIXTURES / "profile_bad_date.cv.txt")
    (issue,) = exc.value.issues
    assert issue.line == 11
    assert "YYYY-MM" in issue.fix


def test_bad_weight_names_bullet() -> None:
    with pytest.raises(CVForgeError) as exc:
        load_profile(FIXTURES / "profile_bad_weight.cv.txt")
    (issue,) = exc.value.issues
    assert issue.item == "exp-01.b1"


def test_duplicate_yaml_key_is_an_error() -> None:
    with pytest.raises(CVForgeError) as exc:
        load_profile(FIXTURES / "profile_bad_yaml.cv.txt")
    assert exc.value.issues[0].line == 4


def test_missing_file_says_how_to_fix(tmp_path: Path) -> None:
    with pytest.raises(CVForgeError) as exc:
        load_profile(tmp_path / "nope.cv.txt")
    assert "cvforge init" in exc.value.issues[0].fix


def test_empty_file_is_an_error() -> None:
    with pytest.raises(CVForgeError):
        parse_text("", "x.cv.txt")


def test_dump_profile_round_trips() -> None:
    p = load_profile(EXAMPLES / "profile.cv.txt").profile
    again = parse_text(dump_profile(p)).profile
    assert again == p


def test_append_skill_keeps_comments() -> None:
    text = (FIXTURES / "profile_min.cv.txt").read_text()
    text = "# my comment\n" + text
    new = append_skill(text, "f", "rust", "Rust")
    assert "# my comment" in new
    assert parse_text(new).profile.skills["rust"] == "Rust"


def test_append_skill_rejects_duplicate() -> None:
    text = (FIXTURES / "profile_min.cv.txt").read_text()
    with pytest.raises(CVForgeError):
        append_skill(text, "f", "py", "Python again")


def test_append_role_and_bullet() -> None:
    text = (FIXTURES / "profile_min.cv.txt").read_text()
    role = Experience(id="exp-02", title="Dev", org="Acme", start="2023-01", end="2023-12")
    text = append_item(text, "f", "experience", role)
    text = append_bullet(text, "f", "exp-02", Bullet(id="b1", text="Shipped it.", skills=["py"]))
    p = parse_text(text).profile
    assert p.experience[1].bullets[0].skills == ["py"]
    assert "skills: [py]" in text


def test_append_bullet_unknown_item_lists_known_ids() -> None:
    text = (FIXTURES / "profile_min.cv.txt").read_text()
    with pytest.raises(CVForgeError) as exc:
        append_bullet(text, "f", "exp-09", Bullet(id="b1", text="x"))
    assert "exp-01" in exc.value.issues[0].fix


def test_next_id() -> None:
    assert next_id(["exp-01", "exp-07"], "exp-") == "exp-08"
    assert next_id([], "exp-") == "exp-01"
    assert next_id(["b1", "b2"], "b", width=0) == "b3"


def test_load_hat() -> None:
    hat = load_hat(EXAMPLES / "hats" / "developer.toml")
    assert hat.skill_weights["py"] == 2.0


def test_hat_unknown_key(tmp_path: Path) -> None:
    f = tmp_path / "h.toml"
    f.write_text('name = "x"\ntitel_line = "y"\n')
    with pytest.raises(CVForgeError) as exc:
        load_hat(f)
    assert exc.value.issues[0].line == 2
