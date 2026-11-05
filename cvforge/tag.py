"""Skill tagging with an LLM: the model proposes skill ids for each bullet; only ids the profile
already declares are kept, existing tags are never removed, and nothing is written without the
user's approval. The model can therefore add evidence links, never new skills or facts."""

from __future__ import annotations

from dataclasses import dataclass, field

from cvforge.errors import CVForgeError, Issue
from cvforge.llm import Client, json_answer
from cvforge.schema import Profile

SYSTEM_PROMPT = (
    "You tag CV bullets with skill ids. Use only the skill ids listed. Tag a bullet with a skill "
    "only when the bullet's own words show that skill being used. Answer with JSON only: "
    '{"tags": {"<bullet id>": ["<skill id>", ...]}}.'
)


@dataclass
class TagProposal:
    qid: str
    text: str
    current: list[str]
    added: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (skill id, reason)

    @property
    def proposed(self) -> list[str]:
        return [*self.current, *self.added]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.qid,
            "current": self.current,
            "added": self.added,
            "rejected": [{"skill": s, "reason": r} for s, r in self.rejected],
        }


def prompt(profile: Profile) -> str:
    skills = "\n".join(f"{sid}: {name}" for sid, name in profile.skills.items())
    bullets = "\n".join(
        f"{item.id}.{b.id}: {b.text}" for item in profile.all_items() for b in item.bullets
    )
    return f"Skill ids:\n{skills}\n\nBullets:\n{bullets}"


def propose_tags(profile: Profile, client: Client, file: str) -> list[TagProposal]:
    answer = json_answer(client.complete(SYSTEM_PROMPT, prompt(profile)))
    tags = answer.get("tags") if isinstance(answer, dict) else None
    if not isinstance(tags, dict):
        raise CVForgeError(
            [
                Issue(
                    file=file,
                    item="tag --llm",
                    message='the model did not answer with {"tags": {...}} JSON.',
                    fix="run again, or try another model in [llm]; nothing was changed.",
                )
            ]
        )
    out = []
    for item in profile.all_items():
        for b in item.bullets:
            qid = f"{item.id}.{b.id}"
            p = TagProposal(qid, b.text, list(b.skills))
            suggested = tags.get(qid) or []
            for sid in suggested if isinstance(suggested, list) else []:
                sid = str(sid)
                if sid not in profile.skills:
                    p.rejected.append((sid, "not a declared skill id in this profile"))
                elif sid not in p.current and sid not in p.added:
                    p.added.append(sid)
            out.append(p)
    return out
