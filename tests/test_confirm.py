"""cvforge confirm: fictional data only. The profile comes from the real importer run on two
fictional Jake's-style CVs that disagree on a phone number, a start date and a bullet."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cvforge import pipeline
from cvforge.cli import app
from cvforge.confirm import questions
from cvforge.errors import CVForgeError
from cvforge.parse import confirm_lines, set_confirmed, split_value_line

from .conftest import FIXTURES

SOURCES = FIXTURES / "confirm"
runner = CliRunner()
EPOCH = "1767312000"  # 2026-01-02 UTC
TODAY = "2026-01-02"


@pytest.fixture
def imported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "profile.cv.txt"
    result = pipeline.import_profiles(
        [SOURCES / "cv-a.tex", SOURCES / "cv-b.tex"], out, None, force=False
    )
    assert result.confirms == 4 and result.confirm == tmp_path / "CONFIRM.md"
    return out


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").split("\n")


def _changed(before: list[str], after: list[str]) -> list[int]:
    assert len(before) == len(after)
    return [n for n, (a, b) in enumerate(zip(before, after, strict=True), start=1) if a != b]


def _cli(*args: str, input: str | None = None) -> tuple[int, str, str]:
    r = runner.invoke(app, list(args), input=input, env={"SOURCE_DATE_EPOCH": EPOCH})
    return r.exit_code, r.stdout, r.stderr


def test_questions_come_from_confirm_md_and_profile(imported: Path) -> None:
    state = pipeline.confirm_pending(imported, None)
    assert [q.number for q in state.questions] == [1, 2, 3, 4]
    phone = state.questions[0]
    assert phone.what == "phone" and phone.where == "person.phone"
    assert _lines(imported)[phone.line - 1].startswith('  phone: "+66 80-000-0000"')
    assert [(o.value, o.sources, o.current) for o in phone.options] == [
        ("+66 80-000-0000", "cv-a.tex:4", True),
        ("080-000-0000", "cv-b.tex:4", False),
    ]
    assert state.questions[1].where == "exp-01 start"
    assert state.questions[3].where == "exp-01.b3 text" and len(state.questions[3].options) == 1


def test_choose_an_option_changes_one_line_only(imported: Path) -> None:
    before = _lines(imported)
    result = pipeline.confirm_answer(imported, None, [(1, "2")], today=TODAY)
    after = _lines(imported)
    assert _changed(before, after) == [7]
    assert after[6] == f'  phone: "080-000-0000"  # source: user {TODAY}'
    assert [q.number for q in result.state.questions] == [2, 3, 4]
    assert result.applied[0][0].choice == 2
    parsed = pipeline.load_valid_profile(imported)  # still parses and validates
    assert parsed.profile.person.phone == "080-000-0000"


def test_type_your_own_value(imported: Path) -> None:
    before = _lines(imported)
    typed = "Ran the documentation build on every release."
    pipeline.confirm_answer(imported, None, [(3, typed)], today=TODAY)
    after = _lines(imported)
    (n,) = _changed(before, after)
    assert after[n - 1] == f'        text: "{typed}"  # source: user {TODAY}'
    assert pipeline.load_valid_profile(imported).profile.experience[0].bullets[1].text == typed


def test_digits_are_a_choice_unless_quoted(imported: Path) -> None:
    pipeline.confirm_answer(imported, None, [(2, '"2023"')], today=TODAY)
    assert pipeline.load_valid_profile(imported).profile.experience[0].start == "2023"


def test_whole_file_is_byte_identical_apart_from_answered_lines(imported: Path) -> None:
    raw = imported.read_bytes().replace(b"\n", b"\r\n")  # a profile saved on Windows
    imported.write_bytes(raw)
    pipeline.confirm_answer(imported, None, [(1, "1"), (2, "2")], today=TODAY)
    new = imported.read_bytes()
    old_lines, new_lines = raw.split(b"\r\n"), new.split(b"\r\n")
    assert len(old_lines) == len(new_lines) and b"\n" not in new.replace(b"\r\n", b"")
    assert [n for n, (a, b) in enumerate(zip(old_lines, new_lines, strict=True), 1) if a != b] == [
        7,
        24,
    ]
    assert new_lines[23] == f'    start: "2023-05"  # source: user {TODAY}'.encode()
    # Choosing the value already there still records the answer.
    assert new_lines[6] == f'  phone: "+66 80-000-0000"  # source: user {TODAY}'.encode()


def test_skip_then_resume(imported: Path) -> None:
    code, stdout, _ = _cli("confirm", "-p", str(imported), input="s\n2\nq\n")
    assert code == 0, stdout
    assert "1 of 4: CONFIRM.md #1" in stdout and "3 of 4: CONFIRM.md #3" in stdout
    assert "2 fact(s)" not in stdout and "3 fact(s) still marked TODO confirm" in stdout
    text = imported.read_text()
    assert f'start: "2023-05"  # source: user {TODAY}' in text
    assert "TODO confirm (CONFIRM.md #1)" in text  # skipped stays open
    code, stdout, _ = _cli("confirm", "-p", str(imported), input="2\ns\ns\n")
    assert code == 0
    assert "1 of 3: CONFIRM.md #1 phone" in stdout  # resumes at the first open entry
    assert "done: 1 answered, 2 skipped" in stdout
    assert [q.number for q in pipeline.confirm_pending(imported, None).questions] == [3, 4]


def test_quit_then_resume(imported: Path) -> None:
    before = imported.read_bytes()
    code, stdout, _ = _cli("confirm", "-p", str(imported), input="q\n")
    assert code == 0 and "stopped: 0 answered" in stdout
    assert imported.read_bytes() == before
    code, stdout, _ = _cli("confirm", "-p", str(imported), input="1\n1\nq\n")
    assert code == 0 and "stopped: 2 answered" in stdout
    code, stdout, _ = _cli("confirm", "-p", str(imported), input="1\n1\n")
    assert "1 of 2: CONFIRM.md #3" in stdout and "nothing left to confirm" in stdout
    pipeline.load_valid_profile(imported)
    assert "TODO confirm (" not in imported.read_text()


def test_invalid_answer_is_refused_and_asked_again(imported: Path) -> None:
    before = imported.read_bytes()
    code, stdout, stderr = _cli("confirm", "-p", str(imported), input="s\nJune 2023\nq\n")
    assert code == 0
    assert "profile.cv.txt:24 [CONFIRM.md #2]: error: the answer `June 2023`" in stderr
    assert "Fix: write it as YYYY-MM" in stderr
    assert stdout.count("2 of 4: CONFIRM.md #2") == 1 and "stopped: 0 answered" in stdout
    assert imported.read_bytes() == before


def test_json_lists_pending(imported: Path) -> None:
    code, stdout, _ = _cli("confirm", "-p", str(imported), "--json")
    assert code == 0
    data = json.loads(stdout)
    assert data["ok"] is True and data["confirm"].endswith("CONFIRM.md")
    first = data["pending"][0]
    assert first["number"] == 1 and first["what"] == "phone" and first["line"] == 7
    assert first["options"][1] == {
        "choice": 2,
        "value": "080-000-0000",
        "sources": "cv-b.tex:4",
        "current": False,
    }


def test_json_answers(imported: Path) -> None:
    code, stdout, _ = _cli(
        "confirm",
        "-p",
        str(imported),
        "--json",
        "--answer",
        "1=2",
        "--answer",
        '3="Ran the documentation build on every release."',
    )
    assert code == 0, stdout
    data = json.loads(stdout)
    assert [(a["number"], a["choice"]) for a in data["applied"]] == [(1, 2), (3, None)]
    assert data["applied"][1]["value"] == "Ran the documentation build on every release."
    assert [q["number"] for q in data["pending"]] == [2, 4]
    assert f"# source: user {TODAY}" in imported.read_text()


@pytest.mark.parametrize(
    ("answer", "item", "message"),
    [
        ("9=1", "CONFIRM.md #9", "entry #9 is not waiting for an answer (open: #1, #2, #3, #4)"),
        ("1=3", "CONFIRM.md #1", "there is no option 3"),
        ("phone", "--answer phone", "an answer is N=CHOICE"),
        ("2=soon", "CONFIRM.md #2", "would make the profile invalid"),
    ],
)
def test_bad_answer_is_a_structured_error(
    imported: Path, answer: str, item: str, message: str
) -> None:
    before = imported.read_bytes()
    code, stdout, _ = _cli("confirm", "-p", str(imported), "--json", "--answer", answer)
    assert code == 1
    data = json.loads(stdout)
    assert data["ok"] is False
    issue = data["issues"][0]
    assert issue["item"] == item and message in issue["message"]
    assert issue["file"].endswith("profile.cv.txt") and issue["fix"]
    assert imported.read_bytes() == before


def test_answers_are_all_or_nothing(imported: Path) -> None:
    before = imported.read_bytes()
    with pytest.raises(CVForgeError):
        pipeline.confirm_answer(imported, None, [(1, "2"), (1, "1")], today=TODAY)
    assert imported.read_bytes() == before


def test_works_without_confirm_md(imported: Path) -> None:
    (imported.parent / "CONFIRM.md").unlink()
    state = pipeline.confirm_pending(imported, None)
    assert state.confirm is None
    phone = state.questions[0]
    assert phone.what == "person.phone"
    assert [(o.value, o.sources) for o in phone.options] == [("+66 80-000-0000", "cv-a.tex:4")]
    pipeline.confirm_answer(imported, None, [(1, '"+66 80 000 0001"')], today=TODAY)
    assert pipeline.load_valid_profile(imported).profile.person.phone == "+66 80 000 0001"


def test_missing_confirm_md_named_on_the_command_line(imported: Path) -> None:
    with pytest.raises(CVForgeError, match=r"CONFIRM\.md not found"):
        pipeline.confirm_pending(imported, imported.parent / "nope.md")


PROFILE_TWO_NUMBERS = """\
person:
  name: "Sam Sample"  # source: cv-x p.1, cv-y p.1
experience:
  - id: exp-01
    title: "Analyst"  # source: cv-x p.1; TODO confirm (CONFIRM.md #1, #2)
    org: "Sample Co"  # source: cv-x p.1
    start: "2022-01"  # source: cv-x p.1
    end: "present"  # source: cv-x p.1
"""

CONFIRM_TWO_NUMBERS = """\
# Facts to confirm

## 1. a experience entry appears only in cv-x p.1

- `Analyst` — cv-x p.1 (in the profile now)

## 2. experience title 'Analyst'

- `Analyst` — cv-x p.1 (in the profile now)
- `Data Analyst` — cv-y p.2

## Not imported

- header line 'Hello' (cv-y p.1) was not imported
"""


def test_a_line_with_two_entries_keeps_the_other_open(tmp_path: Path) -> None:
    profile = tmp_path / "profile.cv.txt"
    profile.write_text(PROFILE_TWO_NUMBERS)
    (tmp_path / "CONFIRM.md").write_text(CONFIRM_TWO_NUMBERS)
    qs = pipeline.confirm_pending(profile, None).questions
    assert [(q.number, len(q.options)) for q in qs] == [(1, 1), (2, 2)]
    pipeline.confirm_answer(profile, None, [(1, "1")], today=TODAY)
    line = profile.read_text().split("\n")[4]
    assert line == f'    title: "Analyst"  # source: user {TODAY}; TODO confirm (CONFIRM.md #2)'
    pipeline.confirm_answer(profile, None, [(2, "2")], today=TODAY)
    line = profile.read_text().split("\n")[4]
    assert line == f'    title: "Data Analyst"  # source: user {TODAY}'
    assert not pipeline.confirm_pending(profile, None).questions


def test_split_value_line_forms() -> None:
    v = split_value_line('  phone: "+66 80"  # source: a; TODO confirm (CONFIRM.md #1)')
    assert v is not None and (v.head, v.value, v.gap) == ("  phone: ", "+66 80", "  ")
    v = split_value_line("    - plain: value: with colon  # note")
    assert v is not None and v.value == "value: with colon"
    v = split_value_line("    text: 'it''s'  # x")
    assert v is not None and v.value == "it's"
    assert split_value_line('  "Languages": [py, go]  # source: a') is None
    assert split_value_line("person:") is None
    assert split_value_line("  # location: TODO") is None


def test_a_line_that_cannot_be_rewritten_names_the_line() -> None:
    text = 'skill_groups:\n  "Langs": [py]  # source: a; TODO confirm (CONFIRM.md #1)\n'
    assert [c.numbers for c in confirm_lines(text, "p.cv.txt")] == [(1,)]
    assert questions(text, "p.cv.txt", None)[0].options == ()
    with pytest.raises(CVForgeError) as exc:
        set_confirmed(text, "p.cv.txt", 2, 1, "Languages", "user 2026-01-02")
    issue = exc.value.issues[0]
    assert issue.line == 2 and issue.item == "CONFIRM.md #1" and "by hand" in issue.fix
