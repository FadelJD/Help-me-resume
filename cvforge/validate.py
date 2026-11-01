"""Cross-checks the schema cannot express: unique ids, skill references, date order, hats."""

from __future__ import annotations

from difflib import get_close_matches

from cvforge.errors import Issue
from cvforge.parse import ParsedProfile
from cvforge.schema import Hat, Profile

SECTIONS = ("experience", "projects", "education")


def _suggest(word: str, skills: dict[str, str]) -> str:
    """Closest skill id, matching the typo against ids and against skill names."""
    by_name = {name.lower(): sid for sid, name in skills.items()}
    close = get_close_matches(word, list(skills), n=1)
    if not close:
        names = get_close_matches(word.lower(), list(by_name), n=1)
        close = [by_name[names[0]]] if names else []
    return f" Did you mean `{close[0]}`?" if close else ""


def validate_profile(parsed: ParsedProfile) -> list[Issue]:
    p = parsed.profile
    src = parsed.source
    issues: list[Issue] = []
    seen_items: dict[str, str] = {}
    used_skills: set[str] = set()

    for section in SECTIONS:
        for i, item in enumerate(getattr(p, section)):
            loc: tuple[str | int, ...] = (section, i)
            if item.id in seen_items:
                issues.append(
                    Issue(
                        file=src.file,
                        line=src.line((*loc, "id")),
                        item=item.id,
                        message=f"id `{item.id}` is used twice (also in {seen_items[item.id]}).",
                        fix="give each role, project and education entry its own id.",
                    )
                )
            seen_items[item.id] = section

            for tag in getattr(item, "tags", []):
                if tag not in p.skills:
                    issues.append(
                        Issue(
                            file=src.file,
                            line=src.line((*loc, "tags")),
                            item=item.id,
                            message=f"tag `{tag}` is not a declared skill id.",
                            fix=f"add `{tag}: <name>` under skills:, or fix the tag."
                            + _suggest(tag, p.skills),
                        )
                    )

            start, end = getattr(item, "start", None), getattr(item, "end", None)
            if start and end and end != "present" and end < start:
                issues.append(
                    Issue(
                        file=src.file,
                        line=src.line((*loc, "end")),
                        item=item.id,
                        message=f"end {end} is before start {start}.",
                        fix="swap the dates or correct the typo.",
                    )
                )

            seen_bullets: set[str] = set()
            for j, b in enumerate(item.bullets):
                bloc = (*loc, "bullets", j)
                qid = f"{item.id}.{b.id}"
                if b.id in seen_bullets:
                    issues.append(
                        Issue(
                            file=src.file,
                            line=src.line((*bloc, "id")),
                            item=qid,
                            message=f"bullet id `{b.id}` is used twice in {item.id}.",
                            fix="give each bullet in an item its own id (b1, b2, ...).",
                        )
                    )
                seen_bullets.add(b.id)
                for s in b.skills:
                    used_skills.add(s)
                    if s not in p.skills:
                        issues.append(
                            Issue(
                                file=src.file,
                                line=src.line((*bloc, "skills")),
                                item=qid,
                                message=f"skill `{s}` is not a declared skill id.",
                                fix=f"add `{s}: <name>` under skills:, or fix the reference."
                                + _suggest(s, p.skills),
                            )
                        )

    for sid, name in p.skills.items():
        if sid not in used_skills:
            issues.append(
                Issue(
                    file=src.file,
                    line=src.line(("skills", sid)),
                    item=sid,
                    severity="warning",
                    message=f"skill `{name}` is not evidenced by any bullet, so it is never shown.",
                    fix=f"add `{sid}` to the skills: of a bullet that shows it.",
                )
            )
    return issues


def validate_hat(hat: Hat, profile: Profile, file: str) -> list[Issue]:
    issues: list[Issue] = []
    for sid in hat.skill_weights:
        if sid not in profile.skills:
            issues.append(
                Issue(
                    file=file,
                    item=hat.name,
                    message=f"skill_weights names `{sid}`, which the profile does not declare.",
                    fix="use a skill id from profile.cv.txt." + _suggest(sid, profile.skills),
                )
            )
    for group, members in hat.skill_groups.items():
        for sid in members:
            if sid not in profile.skills:
                issues.append(
                    Issue(
                        file=file,
                        item=hat.name,
                        message=f"skill_groups.{group} names `{sid}`, which the profile lacks.",
                        fix="use a skill id from profile.cv.txt." + _suggest(sid, profile.skills),
                    )
                )
    if len(set(hat.sections)) != len(hat.sections):
        issues.append(
            Issue(
                file=file,
                item=hat.name,
                message="sections lists a section twice.",
                fix="list each section once.",
            )
        )
    return issues
