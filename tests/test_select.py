from __future__ import annotations

from cvforge.parse import load_hat, load_profile
from cvforge.schema import Hat
from cvforge.select import select

from .conftest import EXAMPLES, FIXTURES

PROFILE = load_profile(EXAMPLES / "profile.cv.txt").profile
DEV = load_hat(EXAMPLES / "hats" / "developer.toml")
BACKEND = (FIXTURES / "job_backend.txt").read_text()
WRITER = (FIXTURES / "job_writer.txt").read_text()


def _order(sel: object, item: str) -> list[str]:
    for si in sel.items():  # type: ignore[attr-defined]
        if si.item.id == item:
            return [b.qid for b in si.bullets]
    raise KeyError(item)


def test_no_hat_ranks_by_weight_only() -> None:
    sel = select(PROFILE)
    assert all(b.parts["hat"] == 1.0 and b.parts["job"] == 0.0 for b in sel.bullets())
    weights = [b.bullet.weight for b in sel.experience[0].bullets]
    assert weights == sorted(weights, reverse=True)


def test_ties_keep_profile_order() -> None:
    sel = select(PROFILE)
    assert _order(sel, "exp-01")[:2] == ["exp-01.b2", "exp-01.b4"]  # both weight 4


def test_two_job_ads_reorder_bullets_under_same_hat() -> None:
    backend = select(PROFILE, DEV, BACKEND)
    writer = select(PROFILE, DEV, WRITER)
    assert _order(backend, "exp-02") != _order(writer, "exp-02")
    assert _order(backend, "exp-02")[0] == "exp-02.b1"  # REST API in Node.js and PostgreSQL
    b1 = {b.qid: b for b in backend.bullets()}["exp-02.b1"]
    w1 = {b.qid: b for b in writer.bullets()}["exp-02.b1"]
    assert b1.parts["job"] > w1.parts["job"]  # explain shows why: the job term differs


def test_max_bullets_drops_with_reason() -> None:
    sel = select(PROFILE, DEV, None, max_bullets=2)
    assert all(len(si.bullets) <= 2 for si in sel.items())
    reasons = [d.reason for d in sel.dropped if d.kind == "bullet"]
    assert reasons and "limit is 2 per role" in reasons[0]


def test_roles_stay_reverse_chronological() -> None:
    sel = select(PROFILE, DEV, WRITER)
    assert [si.item.id for si in sel.experience] == ["exp-01", "exp-02"]


def test_only_evidenced_skills_are_emitted() -> None:
    sel = select(PROFILE, DEV, None, max_bullets=1)
    emitted = {s.id for s in sel.skills}
    evidenced = {s for b in sel.bullets() for s in b.bullet.skills}
    assert emitted == evidenced
    assert all(s.evidence for s in sel.skills)
    assert any(d.kind == "skill" and "not evidenced" in d.reason for d in sel.dropped)


def test_hat_weight_zero_hides_skill() -> None:
    hat = Hat(name="x", skill_weights={"latex": 0.0})
    sel = select(PROFILE, hat)
    assert "latex" not in {s.id for s in sel.skills}
    assert any(d.id == "latex" and "weights it 0" in d.reason for d in sel.dropped)


def test_hat_sections_can_drop_a_section() -> None:
    hat = Hat(name="x", sections=["experience", "skills"])
    sel = select(PROFILE, hat)
    assert sel.projects == [] and sel.education == []
    assert {d.id for d in sel.dropped if d.kind == "section"} == {"projects", "education"}


def test_skill_groups_with_other() -> None:
    hat = Hat(name="x", skill_groups={"Web": ["ts", "react"]})
    sel = select(PROFILE, hat)
    names = [g for g, _ in sel.skill_groups]
    assert names == ["Web", "Other"]


def test_selection_is_deterministic() -> None:
    a = select(PROFILE, DEV, BACKEND, 3)
    b = select(PROFILE, DEV, BACKEND, 3)
    assert [x.qid for x in a.bullets()] == [x.qid for x in b.bullets()]
