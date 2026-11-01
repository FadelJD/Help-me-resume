"""Hat weights + job-ad relevance -> an ordered subset of the profile. No network, no model.

Bullet score = weight (1-5) x hat factor x (1 + job relevance), where the hat factor is the
largest hat weight among the bullet's skills (1.0 without a hat or for unlisted skills) and job
relevance is BM25 against the job ad scaled to 0..1. Roles stay reverse-chronological; bullets
within a role, and projects, are ordered by score.
"""

from __future__ import annotations

from cvforge.schema import (
    Dropped,
    Education,
    Experience,
    Hat,
    Profile,
    Project,
    ScoredBullet,
    SelectedItem,
    SelectedSkill,
    Selection,
)
from cvforge.score import relevance, tokenize

DEFAULT_SECTIONS = ["experience", "projects", "skills", "education"]


def _hat_factor(skills: list[str], hat: Hat | None) -> float:
    if hat is None or not skills:
        return 1.0
    return max(hat.skill_weights.get(s, 1.0) for s in skills)


def _bullet_doc(text: str, skills: list[str], profile: Profile) -> str:
    return " ".join([text, *(profile.skills.get(s, "") for s in skills)])


def _date_key(value: str | None) -> str:
    return "9999-99" if value in (None, "present") else str(value)


def select(
    profile: Profile,
    hat: Hat | None = None,
    job: str | None = None,
    max_bullets: int | None = None,
) -> Selection:
    sections: list[str] = list(hat.sections) if hat else list(DEFAULT_SECTIONS)
    sel = Selection(sections=sections, hat=hat.name if hat else "", max_bullets=max_bullets)
    for section in DEFAULT_SECTIONS:
        if section not in sections and (getattr(profile, section)):
            sel.dropped.append(
                Dropped(section, "section", f"hat `{sel.hat}` does not include {section}")
            )

    items: list[tuple[str, Experience | Project | Education]] = [
        (s, i) for s in ("experience", "projects", "education") for i in getattr(profile, s)
    ]
    flat = [(sec, item, b) for sec, item in items for b in item.bullets]
    rel = (
        relevance([_bullet_doc(b.text, b.skills, profile) for _, _, b in flat], job)
        if job
        else [0.0] * len(flat)
    )
    scored: dict[str, list[ScoredBullet]] = {}
    for (_, item, b), r in zip(flat, rel, strict=True):
        hat_f = _hat_factor(b.skills, hat)
        score = round(b.weight * hat_f * (1 + r), 4)
        parts = {"weight": float(b.weight), "hat": hat_f, "job": r}
        scored.setdefault(item.id, []).append(ScoredBullet(item.id, b, score, parts, b.text))

    for section, item in items:
        if section not in sections:
            continue
        ranked = sorted(scored.get(item.id, []), key=lambda sb: -sb.score)  # stable on ties
        keep = ranked if max_bullets is None else ranked[:max_bullets]
        for pos, sb in enumerate(ranked[len(keep) :], start=len(keep) + 1):
            sel.dropped.append(
                Dropped(
                    sb.qid,
                    "bullet",
                    f"rank {pos} of {len(ranked)} in {item.id} (score {sb.score}); "
                    f"limit is {max_bullets} per role",
                )
            )
        top = max((sb.score for sb in keep), default=0.0)
        getattr(sel, section).append(SelectedItem(section, item, keep, top))

    sel.experience.sort(
        key=lambda si: (_date_key(si.item.end), _date_key(si.item.start)), reverse=True
    )
    sel.projects.sort(key=lambda si: -si.score)
    sel.education.sort(key=lambda si: _date_key(si.item.end), reverse=True)

    _select_skills(sel, profile, hat, job)
    return sel


def _select_skills(sel: Selection, profile: Profile, hat: Hat | None, job: str | None) -> None:
    evidence: dict[str, list[str]] = {}
    strength: dict[str, float] = {}
    for sb in sel.bullets():
        for s in sb.bullet.skills:
            evidence.setdefault(s, []).append(sb.qid)
            strength[s] = strength.get(s, 0.0) + sb.score
    job_terms = set(tokenize(job)) if job else set()
    chosen: list[SelectedSkill] = []
    for sid, name in profile.skills.items():
        weight = hat.skill_weights.get(sid, 1.0) if hat else 1.0
        if sid not in evidence:
            sel.dropped.append(Dropped(sid, "skill", "not evidenced by any selected bullet"))
            continue
        if weight == 0:
            sel.dropped.append(Dropped(sid, "skill", f"hat `{sel.hat}` weights it 0"))
            continue
        mentioned = 1.0 if job_terms and set(tokenize(name)) & job_terms else 0.0
        score = round(weight * strength[sid] * (1 + mentioned), 4)
        chosen.append(SelectedSkill(sid, name, score, evidence[sid]))
    chosen.sort(key=lambda s: -s.score)
    if "skills" not in sel.sections:
        return
    sel.skills = chosen
    if hat and hat.skill_groups:
        by_id = {s.id: s for s in chosen}
        grouped: set[str] = set()
        for group, members in hat.skill_groups.items():
            in_group = [s for s in chosen if s.id in members and s.id in by_id]
            grouped.update(s.id for s in in_group)
            if in_group:
                sel.skill_groups.append((group, in_group))
        rest = [s for s in chosen if s.id not in grouped]
        if rest:
            sel.skill_groups.append(("Other", rest))
