"""First-run questions that produce a profile, cvforge.toml and starter hats.

Every question has a default or can be skipped, so declining to answer never blocks a build.
Input and output are injected (`ask`, `confirm`, `say`) so the flow is testable without a TTY.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from cvforge.schema import YEAR_MONTH, Bullet, Education, Experience, Person, Profile

Ask = Callable[[str, str], str]
Confirm = Callable[[str, bool], bool]
Say = Callable[[str], None]

DEFAULT_HATS: dict[str, str] = {
    "full-stack-engineer": "Full-Stack Engineer",
    "developer": "Software Developer",
    "technical-writer": "Technical Writer",
}


@dataclass
class InitResult:
    profile: Profile
    template: str = ""
    hat: str = ""
    locale: str = "th"
    hats: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HATS))


def skill_id(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "skill"
    candidate, n = base, 2
    while candidate in taken:
        candidate, n = f"{base}-{n}", n + 1
    return candidate


def _ask_date(ask: Ask, say: Say, prompt: str, default: str, allow_present: bool) -> str:
    while True:
        value = ask(prompt, default).strip()
        if YEAR_MONTH.match(value) or (allow_present and value == "present"):
            return value
        say("  Use YYYY-MM" + (" or present" if allow_present else "") + ", e.g. 2025-06.")


def _resolve_skills(raw: str, skills: dict[str, str], say: Say) -> list[str]:
    """Map comma-separated ids or names to ids, adding unknown names as new skills."""
    out: list[str] = []
    by_name = {v.lower(): k for k, v in skills.items()}
    for part in (p.strip() for p in raw.split(",")):
        if not part:
            continue
        if part in skills:
            sid = part
        elif part.lower() in by_name:
            sid = by_name[part.lower()]
        else:
            sid = skill_id(part, set(skills))
            skills[sid] = part
            by_name[part.lower()] = sid
            say(f"  added skill {sid}: {part}")
        if sid not in out:
            out.append(sid)
    return out


def run_interview(ask: Ask, confirm: Confirm, say: Say, today: date | None = None) -> InitResult:
    today = today or date.today()
    this_month = today.strftime("%Y-%m")
    say("About you. Press Enter to accept the default shown in brackets or to skip.")
    name = ask("Full name", "Your Name").strip() or "Your Name"
    email = ask("Email (Enter to skip)", "").strip() or None
    phone = ask("Phone (Enter to skip)", "").strip() or None
    location = ask("City, country (Enter to skip)", "").strip() or None
    links_raw = ask("Links, comma separated, e.g. github.com/you (Enter to skip)", "")
    links = [x.strip() for x in links_raw.split(",") if x.strip()]

    skills: dict[str, str] = {}
    say("Skills. Name them as they should appear on the CV, comma separated.")
    _resolve_skills(ask("Skills (Enter to skip)", ""), skills, say)

    experience: list[Experience] = []
    while confirm("Add a role?", not experience):
        n = len(experience) + 1
        title = ask("  Job title", "").strip()
        org = ask("  Employer", "").strip()
        if not title or not org:
            say("  A role needs a title and an employer; skipped.")
            continue
        start = _ask_date(ask, say, "  Start (YYYY-MM)", this_month, allow_present=False)
        end = _ask_date(ask, say, "  End (YYYY-MM or present)", "present", allow_present=True)
        bullets: list[Bullet] = []
        while confirm("  Add a bullet for this role?", not bullets):
            text = ask("    What did you do? One line, with a result if you have one", "").strip()
            if not text:
                break
            shown = _resolve_skills(
                ask("    Which skills does it show? (comma separated, Enter for none)", ""),
                skills,
                say,
            )
            weight_raw = ask("    How strong is it, 1-5", "3").strip()
            weight = int(weight_raw) if weight_raw.isdigit() and 1 <= int(weight_raw) <= 5 else 3
            bullets.append(
                Bullet(id=f"b{len(bullets) + 1}", text=text, skills=shown, weight=weight)
            )
        experience.append(
            Experience(
                id=f"exp-{n:02d}", title=title, org=org, start=start, end=end, bullets=bullets
            )
        )

    education: list[Education] = []
    while confirm("Add education?", not education):
        degree = ask("  Degree or certificate", "").strip()
        org = ask("  Institution", "").strip()
        if not degree or not org:
            say("  Education needs a degree and an institution; skipped.")
            continue
        end = _ask_date(ask, say, "  Finished (YYYY-MM or present)", this_month, allow_present=True)
        education.append(
            Education(id=f"edu-{len(education) + 1:02d}", degree=degree, org=org, end=end)
        )

    profile = Profile(
        person=Person(name=name, email=email, phone=phone, location=location, links=links),
        skills=skills,
        experience=experience,
        education=education,
    )
    say("Project defaults (saved to cvforge.toml).")
    template = ask("LaTeX template path (Enter to set later)", "").strip()
    hat = ask(f"Default hat ({', '.join(DEFAULT_HATS)})", "developer").strip()
    locale = ask("Locale (au, uk, us, th)", "th").strip()
    if locale not in ("au", "uk", "us", "th"):
        say("  Unknown locale; using th.")
        locale = "th"
    return InitResult(profile=profile, template=template, hat=hat, locale=locale)


def hat_text(name: str, title_line: str, profile: Profile) -> str:
    """Starter hat: every declared skill at weight 1.0, ready to tune. Holds no facts."""
    lines = [
        "# Weights skills and section order for a role family. Holds no facts about the person.",
        "# Raise weights for skills this role family values (2.0), lower the rest (0.5).",
        f'name = "{name}"',
        f'title_line = "{title_line}"',
        'sections = ["experience", "projects", "skills", "education"]',
        "",
        "[skill_weights]",
    ]
    lines += [f"{sid} = 1.0" for sid in profile.skills]
    return "\n".join(lines) + "\n"
