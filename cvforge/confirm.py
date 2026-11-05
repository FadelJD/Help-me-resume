"""cvforge confirm: settle the facts `cvforge import` could not, one question at a time.

The state lives in the profile itself: a line still marked `# TODO confirm (CONFIRM.md #N)` is an
open question; answering it writes the value on that line and stamps the comment
`# source: user YYYY-MM-DD`. CONFIRM.md, when present, supplies what each question is about and
the competing values with their sources; without it the profile line alone is enough.

Text in, text out: no files are read or written here (pipeline does that).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from cvforge.errors import CVForgeError, Issue, errors_only
from cvforge.importer import read_confirm_markdown
from cvforge.parse import confirm_lines, parse_text, set_confirmed
from cvforge.validate import validate_profile


@dataclass(frozen=True)
class Option:
    value: str
    sources: str
    current: bool  # the value the profile carries now


@dataclass(frozen=True)
class Question:
    number: int  # the CONFIRM.md entry number
    what: str
    where: str  # e.g. person.phone, exp-01 start
    lines: tuple[int, ...]  # profile lines carrying this number (1-based)
    options: tuple[Option, ...]

    @property
    def line(self) -> int:
        return self.lines[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "what": self.what,
            "where": self.where,
            "line": self.line,
            "lines": list(self.lines),
            "options": [
                {"choice": k, "value": o.value, "sources": o.sources, "current": o.current}
                for k, o in enumerate(self.options, start=1)
            ],
        }


@dataclass(frozen=True)
class Answer:
    number: int
    value: str
    choice: int | None  # the option number chosen, or None for a typed value

    def to_dict(self) -> dict[str, Any]:
        return {"number": self.number, "value": self.value, "choice": self.choice}


def questions(profile_text: str, file: str, confirm_text: str | None) -> list[Question]:
    """The open questions, lowest number first."""
    entries = read_confirm_markdown(confirm_text) if confirm_text is not None else {}
    by_number: dict[int, list[Any]] = {}
    for cl in confirm_lines(profile_text, file):
        for n in cl.numbers:
            by_number.setdefault(n, []).append(cl)
    out: list[Question] = []
    for n in sorted(by_number):
        lines = by_number[n]
        first = lines[0]
        current = first.value
        entry = entries.get(n)
        options: list[tuple[str, str]] = list(entry.options) if entry is not None else []
        if current is not None and all(v != current for v, _ in options):
            options.insert(0, (current, first.sources or f"{file}:{first.line}"))
        out.append(
            Question(
                number=n,
                what=entry.what if entry is not None else first.where,
                where=first.where,
                lines=tuple(cl.line for cl in lines),
                options=tuple(Option(v, s, v == current) for v, s in options),
            )
        )
    return out


def parse_answer_arg(arg: str, file: str) -> tuple[int, str]:
    """`--answer 1=2` or `--answer 1="text"` -> (1, '2') or (1, '"text"')."""
    number, sep, raw = arg.partition("=")
    if not sep or not re.fullmatch(r"\s*#?[0-9]+\s*", number):
        raise CVForgeError(
            [
                Issue(
                    file=file,
                    item=f"--answer {arg}",
                    message='an answer is N=CHOICE or N="typed value".',
                    fix='write it as --answer 1=2 (option 2 of entry 1) or --answer 1="value".',
                )
            ]
        )
    return int(number.strip().lstrip("#")), raw


def resolve(question: Question, raw: str, file: str) -> Answer:
    """A number picks that option; anything else is a typed value. Quotes force a typed value."""
    text = raw.strip()
    where = f"CONFIRM.md #{question.number}"
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        typed = text[1:-1].strip()
    elif re.fullmatch(r"[0-9]+", text):
        k = int(text)
        if not 1 <= k <= len(question.options):
            last = len(question.options)
            choices = f"1 to {last}" if last > 1 else "1"
            raise CVForgeError(
                [
                    Issue(
                        file=file,
                        line=question.line,
                        item=where,
                        message=f"there is no option {k}; entry #{question.number} has "
                        f"{last} option{'s' if last != 1 else ''}.",
                        fix=f'choose {choices}, or type the value in quotes, e.g. "{k}".',
                    )
                ]
            )
        return Answer(question.number, question.options[k - 1].value, k)
    else:
        typed = text
    if not typed:
        raise CVForgeError(
            [
                Issue(
                    file=file,
                    line=question.line,
                    item=where,
                    message="the answer is empty.",
                    fix="choose an option by number, or type the value to keep.",
                )
            ]
        )
    if "\n" in typed or "\r" in typed:
        raise CVForgeError(
            [
                Issue(
                    file=file,
                    line=question.line,
                    item=where,
                    message="the typed value has a line break.",
                    fix="give the value on one line.",
                )
            ]
        )
    return Answer(question.number, typed, None)


def _errors(text: str, file: str) -> set[Issue]:
    try:
        parsed = parse_text(text, file)
    except CVForgeError as exc:
        return set(errors_only(exc.issues))
    return set(errors_only(validate_profile(parsed)))


def apply_answer(text: str, file: str, question: Question, answer: Answer, stamp: str) -> str:
    """`text` with the answer written on each of the question's lines.

    Refuses (raises) when the result would not parse, or would have a validation error the
    profile did not already have. Errors the import left (TODO lines) do not block an answer.
    """
    new = text
    for line in question.lines:
        new = set_confirmed(new, file, line, question.number, answer.value, stamp)
    before = _errors(text, file)
    added = sorted(_errors(new, file) - before, key=lambda i: (i.line or 0, i.message))
    if added:
        raise CVForgeError(
            [
                Issue(
                    file=file,
                    line=issue.line or question.line,
                    item=f"CONFIRM.md #{question.number}",
                    message=f"the answer `{answer.value}` would make the profile invalid: "
                    f"{issue.message}",
                    fix=f"{issue.fix} Nothing was written.",
                )
                for issue in added
            ]
        )
    return new
