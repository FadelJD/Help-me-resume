"""The fictional people in examples/people/: valid profiles, job ads that reorder bullets under one
hat, and saved `explain` fixtures that still match what the pipeline produces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cvforge import pipeline
from cvforge.parse import load_hat, load_profile
from cvforge.select import select
from cvforge.validate import validate_profile

from .conftest import EXAMPLES, ROOT

PEOPLE_DIR = EXAMPLES / "people"
TEMPLATE = Path("templates/minimal.tex")
MAX_BULLETS = 5  # matches `max-bullets-per-role` in templates/minimal.tex

# person -> the two job ads (stems under jobs/) that should pull different bullets to the top
PEOPLE: dict[str, tuple[str, str]] = {
    "backend-developer": ("api-platform", "infrastructure"),
    "technical-writer": ("api-reference", "tutorials-onboarding"),
    "data-analyst": ("bi-dashboards", "experimentation"),
    "marketing-manager": ("brand-content", "performance-marketing"),
}
CASES = [(person, job) for person, jobs in PEOPLE.items() for job in jobs]


def _rel(person: str, *parts: str) -> Path:
    """A path relative to the repo root, as the saved fixtures were generated."""
    return Path("examples", "people", person, *parts)


def _order(person: str, job: str) -> dict[str, list[str]]:
    folder = PEOPLE_DIR / person
    profile = load_profile(folder / "profile.cv.txt").profile
    hat = load_hat(folder / "hat.toml")
    ad = (folder / "jobs" / f"{job}.txt").read_text(encoding="utf-8")
    sel = select(profile, hat, ad, max_bullets=MAX_BULLETS)
    return {si.item.id: [sb.qid for sb in si.bullets] for si in sel.items()}


def test_every_person_folder_is_covered() -> None:
    folders = {p.name for p in PEOPLE_DIR.iterdir() if (p / "profile.cv.txt").exists()}
    assert folders == set(PEOPLE)


@pytest.mark.parametrize("person", PEOPLE)
def test_profile_validates_without_issues(person: str) -> None:
    parsed = load_profile(PEOPLE_DIR / person / "profile.cv.txt")
    assert validate_profile(parsed) == []


@pytest.mark.parametrize("person", PEOPLE)
def test_two_job_ads_reorder_bullets(person: str) -> None:
    first, second = PEOPLE[person]
    a, b = _order(person, first), _order(person, second)
    assert a.keys() == b.keys()
    differing = [item for item in a if a[item] != b[item]]
    assert differing, f"{first} and {second} produce the same bullet order for {person}"
    # the strongest point of the most recent role should change with the ad
    assert a["exp-01"][0] != b["exp-01"][0]


@pytest.mark.parametrize(("person", "job"), CASES)
def test_saved_explain_json_matches_pipeline(
    person: str, job: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    result = pipeline.explain(
        profile=_rel(person, "profile.cv.txt"),
        template=TEMPLATE,
        hat=str(_rel(person, "hat.toml")),
        job=str(_rel(person, "jobs", f"{job}.txt")),
        max_bullets=None,
    )
    saved = json.loads((PEOPLE_DIR / person / "explain" / f"{job}.json").read_text("utf-8"))
    assert result.to_dict() == saved, (
        f"examples/people/{person}/explain/{job}.json is stale; regenerate it with "
        f"`cvforge explain --json -p {_rel(person, 'profile.cv.txt')} "
        f"--hat {_rel(person, 'hat.toml')} --job {_rel(person, 'jobs', job + '.txt')} "
        f"-t {TEMPLATE}`"
    )
