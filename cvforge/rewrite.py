"""Optional LLM rewording of selected bullets. The model may reword and reorder, never add.

Every rewrite is diffed against its source: the bullet's text plus the names of the skills the
bullet declares. Any number, date, month, tool-like token, capitalised name or known tool/employer
in the rewrite that the source lacks rejects the rewrite automatically. When unsure, it rejects.
"""

from __future__ import annotations

import importlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

from cvforge.errors import CVForgeError, Issue
from cvforge.schema import Profile, SelectedItem, Selection

SYSTEM_PROMPT = """You reword CV bullet points for a specific job ad.
Rules:
- Keep every fact. Add nothing: no number, percentage, date, tool, technology, product, employer,
  team size, or claim that is not in the original bullet.
- You may reorder clauses and swap in the job ad's wording only where the original supports it.
- One line, past tense, start with a strong verb, at most 30 words.
Reply with the rewritten bullet only, no quotes or commentary."""

MONTHS = {
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
    "january",
    "february",
    "march",
    "april",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}
NUMBER_WORDS = {
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "twenty",
    "thirty",
    "fifty",
    "hundred",
    "hundreds",
    "thousand",
    "thousands",
    "million",
    "millions",
    "billion",
    "dozen",
    "dozens",
    "double",
    "doubled",
    "triple",
    "tripled",
    "half",
    "halved",
}
# Common tools and platforms written in lower case; adding one the source lacks is adding a fact.
TECH_LEXICON = {
    "python",
    "java",
    "javascript",
    "typescript",
    "go",
    "golang",
    "rust",
    "ruby",
    "php",
    "kotlin",
    "swift",
    "scala",
    "react",
    "angular",
    "vue",
    "svelte",
    "django",
    "flask",
    "fastapi",
    "spring",
    "rails",
    "laravel",
    "node",
    "nodejs",
    "express",
    "nextjs",
    "postgres",
    "postgresql",
    "mysql",
    "sqlite",
    "mongodb",
    "redis",
    "kafka",
    "rabbitmq",
    "elasticsearch",
    "docker",
    "kubernetes",
    "k8s",
    "helm",
    "terraform",
    "ansible",
    "aws",
    "azure",
    "gcp",
    "lambda",
    "linux",
    "git",
    "github",
    "gitlab",
    "jenkins",
    "graphql",
    "grpc",
    "rest",
    "spark",
    "hadoop",
    "airflow",
    "pandas",
    "numpy",
    "pytorch",
    "tensorflow",
    "llm",
    "openai",
    "sql",
    "nosql",
    "html",
    "css",
    "tailwind",
    "figma",
    "jira",
    "confluence",
    "markdown",
    "latex",
    "docfx",
    "sphinx",
    "mkdocs",
    "swagger",
    "openapi",
    "salesforce",
    "sap",
    "excel",
    "tableau",
    "powerbi",
    "snowflake",
    "dbt",
    "bigquery",
    "firebase",
    "supabase",
    "vercel",
    "netlify",
    "cloudflare",
    "nginx",
}
# Opening verbs a rewrite may use even when the source does not contain them.
ACTION_VERBS = {
    "achieved",
    "added",
    "automated",
    "boosted",
    "built",
    "championed",
    "coached",
    "collaborated",
    "consolidated",
    "created",
    "cut",
    "debugged",
    "decreased",
    "delivered",
    "deployed",
    "designed",
    "developed",
    "documented",
    "drove",
    "eliminated",
    "enabled",
    "engineered",
    "established",
    "expanded",
    "facilitated",
    "grew",
    "guided",
    "headed",
    "implemented",
    "improved",
    "increased",
    "initiated",
    "integrated",
    "introduced",
    "launched",
    "led",
    "maintained",
    "managed",
    "mentored",
    "migrated",
    "modernised",
    "modernized",
    "optimised",
    "optimized",
    "orchestrated",
    "organised",
    "organized",
    "overhauled",
    "owned",
    "partnered",
    "pioneered",
    "produced",
    "reduced",
    "refactored",
    "replaced",
    "resolved",
    "restructured",
    "revamped",
    "rewrote",
    "ran",
    "scaled",
    "shipped",
    "simplified",
    "spearheaded",
    "standardised",
    "standardized",
    "streamlined",
    "strengthened",
    "supported",
    "trained",
    "transformed",
    "translated",
    "typeset",
    "unified",
    "upgraded",
    "wrote",
    "authored",
    "containerised",
    "containerized",
    "interviewed",
    "published",
    "tested",
    "converted",
}

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#./%,'-]*[A-Za-z0-9+#%]|[A-Za-z0-9]")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?(?:%|[kmx](?![a-z])|\+)?", re.IGNORECASE)


def _numbers(text: str) -> set[str]:
    return {re.sub(r"[,\s]", "", m.group(0)).lower() for m in _NUMBER.finditer(text)}


def _words(text: str) -> list[str]:
    return [w.strip(".,;:'") for w in _WORD.findall(text)]


def _sentence_starts(text: str) -> set[int]:
    """Indexes in _words(text) that open a sentence."""
    starts = {0}
    for idx, raw in enumerate(_WORD.finditer(text), start=1):
        tail = text[raw.end() : raw.end() + 2]
        if tail[:1] in ".!?;:" and (len(tail) < 2 or tail[1] == " "):
            starts.add(idx)
    return starts


def _techy(word: str) -> bool:
    inner = word[1:]
    return (
        any(c.isdigit() for c in word)
        or any(c in word for c in "#+/")
        or ("." in word.strip("."))
        or any(c.isupper() for c in inner)
        or (len(word) >= 2 and word.isupper())
    )


def find_new_facts(source: str, rewrite: str, vocabulary: set[str]) -> list[str]:
    """Facts in `rewrite` absent from `source`; `vocabulary` is lowercased tool/org words."""
    src_words = {w.lower() for w in _words(source)}
    src_words |= {part for w in list(src_words) for part in w.split("-") if part}
    new: list[str] = []

    def flag(token: str) -> None:
        if token not in new:
            new.append(token)

    src_nums = _numbers(source)
    for n in _numbers(rewrite):
        if n not in src_nums:
            flag(n)
    words = _words(rewrite)
    starts = _sentence_starts(rewrite)

    def judge(word: str, opens_sentence: bool) -> None:
        low = word.lower()
        if not low or any(c.isdigit() for c in low) or low in src_words:
            return  # numbers are handled above
        parts = [p for p in word.split("-") if p]
        if len(parts) > 1:
            for part in parts:  # a compound is as new as its newest part
                judge(part, opens_sentence=False)
            return
        known_kind = (
            low in MONTHS or low in NUMBER_WORDS or low in TECH_LEXICON or low in vocabulary
        )
        opening_verb = opens_sentence and low in ACTION_VERBS
        name_like = word[0].isupper() and not opening_verb
        if known_kind or _techy(word) or name_like:
            flag(word)

    for i, word in enumerate(words):
        judge(word, opens_sentence=i in starts)
    return new


def profile_vocabulary(profile: Profile) -> set[str]:
    """Lowercased words naming the person's tools and employers anywhere in the profile."""
    words: set[str] = set()
    for name in profile.skills.values():
        words.update(w.lower() for w in _words(name) if len(w) > 1)
    for item in profile.all_items():
        org = getattr(item, "org", None)
        if org:
            words.update(w.lower() for w in _words(org) if len(w) > 2)
    return words


class Rewriter(Protocol):
    def rewrite(self, text: str, *, job: str, title_line: str) -> str: ...


@dataclass
class CannedRewriter:
    """Returns prepared answers; used by tests and for dry runs."""

    answers: dict[str, str]

    def rewrite(self, text: str, *, job: str, title_line: str) -> str:
        return self.answers.get(text, text)


@dataclass
class LiteLLMRewriter:
    model: str
    api_key_env: str = ""
    _completion: Callable[..., Any] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        try:
            module = importlib.import_module("litellm")
        except ImportError as exc:
            raise CVForgeError(
                [
                    Issue(
                        file="cvforge.toml",
                        message="--rewrite needs LiteLLM, which is not installed.",
                        fix="pip install 'cvforge[llm]'.",
                    )
                ]
            ) from exc
        self._completion = module.completion

    def rewrite(self, text: str, *, job: str, title_line: str) -> str:
        assert self._completion is not None
        kwargs: dict[str, Any] = {}
        if self.api_key_env:
            key = os.environ.get(self.api_key_env)
            if not key:
                raise CVForgeError(
                    [
                        Issue(
                            file="cvforge.toml",
                            message=f"llm.api_key_env names {self.api_key_env}, which is not set.",
                            fix=f"export {self.api_key_env}=... or clear api_key_env.",
                        )
                    ]
                )
            kwargs["api_key"] = key
        user = (
            f"Job ad (vocabulary only):\n{job[:6000]}\n\n"
            f"Target role: {title_line or 'as in the job ad'}\n\nOriginal bullet:\n{text}"
        )
        resp = self._completion(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0,
            **kwargs,
        )
        content = resp.choices[0].message.content or ""
        return " ".join(str(content).strip().strip('"').split())


@dataclass
class Proposal:
    qid: str
    original: str
    rewritten: str
    new_facts: list[str]
    status: str = "pending"  # pending | accepted | rejected | auto-rejected | unchanged

    @property
    def valid(self) -> bool:
        return self.status == "pending"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.qid,
            "original": self.original,
            "rewritten": self.rewritten,
            "status": self.status,
            "new_facts": self.new_facts,
        }


def propose(
    selection: Selection,
    profile: Profile,
    rewriter: Rewriter,
    *,
    job: str,
    title_line: str,
) -> list[Proposal]:
    vocab = profile_vocabulary(profile)
    proposals = []
    for sb in selection.bullets():
        source = " ".join([sb.bullet.text, *(profile.skills[s] for s in sb.bullet.skills)])
        new_text = rewriter.rewrite(sb.bullet.text, job=job, title_line=title_line)
        new_text = " ".join(new_text.split())
        if not new_text or new_text == sb.bullet.text:
            proposals.append(Proposal(sb.qid, sb.bullet.text, sb.bullet.text, [], "unchanged"))
            continue
        facts = find_new_facts(source, new_text, vocab)
        too_long = len(new_text) > max(2 * len(sb.bullet.text), 240)
        if too_long:
            facts.append("(rewrite is more than twice as long)")
        status = "auto-rejected" if facts else "pending"
        proposals.append(Proposal(sb.qid, sb.bullet.text, new_text, facts, status))
    return proposals


def apply(selection: Selection, proposals: list[Proposal]) -> Selection:
    """Replace the emitted text of accepted bullets; ids and order stay the same."""
    accepted = {p.qid: p.rewritten for p in proposals if p.status == "accepted"}

    def swap(item: SelectedItem) -> SelectedItem:
        bullets = [replace(b, text=accepted.get(b.qid, b.text)) for b in item.bullets]
        return replace(item, bullets=bullets)

    return replace(
        selection,
        experience=[swap(i) for i in selection.experience],
        projects=[swap(i) for i in selection.projects],
        education=[swap(i) for i in selection.education],
    )
