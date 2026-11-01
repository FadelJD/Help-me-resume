"""Compile, extract with real parsers, assert every emitted fact came back, score -> Report.

The round-trip needs no model: for each parser it asserts that the name, contact details, every
title, org and date, the first eight words of every bullet, and every skill name survive
extraction as whole words. Each fact is judged in three steps (rules derived from the template
corpus; see docs/parser-table.md and DECISIONS.md):

1. intact: found as whole words, ignoring case (templates restyle case; letters survive);
2. glued: found only with some inter-word spaces missing, still aligned to word boundaries.
   A warning, not a failure: the characters and their order are intact;
3. otherwise lost. A fact touching junk (an icon glyph, a neighbouring word) or with spaces
   inserted inside words counts as lost, because a parser reading it gets the wrong value.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from cvforge.compile import compile_pdf
from cvforge.config import ParserSetting, Thresholds
from cvforge.errors import CVForgeError, Issue
from cvforge.parsers import PARSER_NAMES, Parser, all_parsers
from cvforge.score import Encoder, keyword_coverage, semantic_similarity
from cvforge.template import lint

_CHARMAP = str.maketrans(
    {
        **dict.fromkeys([0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212], "-"),  # dashes
        **dict.fromkeys([0x2018, 0x2019], "'"),  # curly single quotes
        **dict.fromkeys([0x201C, 0x201D], '"'),  # curly double quotes
        0x02DC: "~",  # small tilde
        0x00A0: " ",  # no-break space
        0x00AD: "-",  # soft hyphen: LuaLaTeX maps the visible hyphen to it (Awesome-CV)
    }
)
_CID = re.compile(r"\(cid:\d+\)")
JUNK = "�"


def normalize(text: str) -> str:
    text = _CID.sub(JUNK, text)
    text = unicodedata.normalize("NFKC", text).translate(_CHARMAP)
    return re.sub(r"-{2,}", "-", text)


def squash(text: str) -> str:
    return " ".join(text.split())


def extracted_variants(raw: str) -> list[str]:
    """Readings of line ends: hyphen as soft (join) or real (keep), and long tokens rejoined."""
    text = normalize(raw)
    joined = re.sub(r"-\n(?=[a-z])", "", text)
    kept = re.sub(r"-\n", "-", text)
    # A long token (URL, path) wrapped at one of escape.py's break points: rejoin it.
    unwrapped = re.sub(r"(?<=[/._?&=#@:,;])\n", "", kept)
    return [squash(joined), squash(kept), squash(unwrapped)]


def _is_junk(ch: str) -> bool:
    return ch == JUNK or unicodedata.category(ch) in ("Co", "Cn", "Cc")


def _glued(neighbour: str, edge: str) -> bool:
    return _is_junk(neighbour) or (neighbour.isalnum() and edge.isalnum())


def contains_word(haystack: str, needle: str) -> bool:
    if not needle:
        return True
    start = 0
    while (i := haystack.find(needle, start)) != -1:
        before = haystack[i - 1] if i > 0 else " "
        j = i + len(needle)
        after = haystack[j] if j < len(haystack) else " "
        if not _glued(before, needle[0]) and not _glued(after, needle[-1]):
            return True
        start = i + 1
    return False


def contains_glued(haystack: str, needle: str, open_end: bool = False) -> bool:
    """The needle with some of its spaces missing in the haystack, aligned to word boundaries.

    The haystack may drop spaces the needle has ("AcmeSoftware") but may not add spaces inside
    the needle's words ("T echnical"), and the match may not touch junk or another word.
    With `open_end` (the needle is the start of a longer text, like a bullet's first eight
    words) the match may run straight into the next glued word.
    """
    want = needle.replace(" ", "")
    if not want or want == needle:
        return False
    needle_spaces: set[int] = set()
    k = 0
    for ch in needle:
        if ch == " ":
            needle_spaces.add(k)
        else:
            k += 1
    chars: list[str] = []
    space_before: list[bool] = []
    pending = True
    for ch in haystack:
        if ch == " ":
            pending = True
            continue
        chars.append(ch)
        space_before.append(pending)
        pending = False
    flat = "".join(chars)
    start = 0
    while (i := flat.find(want, start)) != -1:
        j = i + len(want)
        ok_start = i == 0 or space_before[i] or not _glued(flat[i - 1], want[0])
        ok_end = open_end or j == len(flat) or space_before[j] or not _glued(flat[j], want[-1])
        inner = {m - i for m in range(i + 1, j) if space_before[m]}
        if ok_start and ok_end and inner <= needle_spaces:
            return True
        start = i + 1
    return False


def interleaved(haystack: str, needle: str) -> bool:
    """The needle's words appear in order but with other text between them (merged columns)."""
    words = needle.split()
    tokens = haystack.split()
    if len(words) < 2:
        return False
    window = 3 * len(words) + 4
    for i, tok in enumerate(tokens):
        if tok != words[0]:
            continue
        pos, k = i + 1, 1
        while k < len(words) and pos < min(len(tokens), i + window):
            if tokens[pos] == words[k]:
                k += 1
            pos += 1
        if k == len(words):
            return True
    return False


def dates_separated(raw: str, items: list[dict[str, Any]]) -> tuple[int, int]:
    """How many experience titles are more than one line away from their start date."""
    lines = [squash(normalize(line)).casefold() for line in raw.splitlines()]
    lines = [line for line in lines if line]
    checked = separated = 0
    for item in items:
        if item.get("section") != "experience" or not item.get("start"):
            continue
        title = squash(normalize(item["title"])).casefold()
        date = squash(normalize(item["start"])).casefold()
        t_idx = [i for i, line in enumerate(lines) if title in line]
        d_idx = [i for i, line in enumerate(lines) if date in line]
        if not t_idx or not d_idx:
            continue
        checked += 1
        if min(abs(t - d) for t in t_idx for d in d_idx) > 1:
            separated += 1
    return separated, checked


def garbled_count(raw: str) -> int:
    text = _CID.sub(JUNK, raw)
    return sum(1 for ch in text if _is_junk(ch) and ch not in "\n\r\t\f")


@dataclass(frozen=True)
class Fact:
    item: str
    field: str
    expected: str


@dataclass(frozen=True)
class Miss:
    fact: Fact
    found: str | None  # the closest span the parser returned instead, if any
    kind: str = "lost"  # lost | garbled | interleaved | glued (glued is a warning)


@dataclass
class ParserResult:
    name: str
    gate: bool = True
    skipped: str | None = None
    misses: list[Miss] = field(default_factory=list)
    glued: list[Miss] = field(default_factory=list)  # warnings: spaces missing, text intact
    garbled: int = 0
    checked: int = 0
    dates_separated: int = 0
    dates_checked: int = 0

    @property
    def ok(self) -> bool:
        return self.skipped is None and not self.misses

    @property
    def ran(self) -> bool:
        return self.skipped is None


@dataclass
class CheckReport:
    tex: Path
    pdf: Path | None
    parsers: list[ParserResult]
    scores: dict[str, Any]
    density: dict[str, Any]
    warnings: list[Issue]
    strict_failures: list[str]
    lint: list[Issue] = field(default_factory=list)

    @property
    def gating(self) -> list[ParserResult]:
        return [p for p in self.parsers if p.gate and p.ran]

    @property
    def advisory(self) -> list[ParserResult]:
        return [p for p in self.parsers if not p.gate and p.ran]

    @property
    def roundtrip_ok(self) -> bool:
        return bool(self.gating) and all(p.ok for p in self.gating)

    @property
    def ok(self) -> bool:
        return self.roundtrip_ok and not self.strict_failures

    @property
    def badge(self) -> str:
        parts = [f"parsed: {sum(p.ok for p in self.gating)}/{len(self.gating)}"]
        if self.advisory:
            parts.append(f"advisory: {sum(p.ok for p in self.advisory)}/{len(self.advisory)}")
        if self.scores.get("keyword") is not None:
            parts.append(f"keyword: {self.scores['keyword']:.2f}")
        if self.scores.get("semantic") is not None:
            parts.append(f"semantic: {self.scores['semantic']:.2f}")
        if self.scores.get("evidence") is not None:
            parts.append(f"evidence: {self.scores['evidence']:.0%}")
        return " · ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "roundtrip_ok": self.roundtrip_ok,
            "tex": str(self.tex),
            "pdf": str(self.pdf) if self.pdf else None,
            "badge": self.badge,
            "parsers": [
                {
                    "name": p.name,
                    "gate": p.gate,
                    "ok": p.ok,
                    "skipped": p.skipped,
                    "checked": p.checked,
                    "garbled_glyphs": p.garbled,
                    "dates_separated": p.dates_separated,
                    "dates_checked": p.dates_checked,
                    "misses": [_miss_dict(m) for m in p.misses],
                    "glued": [_miss_dict(m) for m in p.glued],
                }
                for p in self.parsers
            ],
            "scores": self.scores,
            "density": self.density,
            "strict_failures": self.strict_failures,
            "warnings": [w.to_dict() for w in self.warnings],
            "lint": [i.to_dict() for i in self.lint],
        }


def _miss_dict(m: Miss) -> dict[str, Any]:
    return {
        "item": m.fact.item,
        "field": m.fact.field,
        "expected": m.fact.expected,
        "found": m.found,
        "kind": m.kind,
    }


def load_report(tex: Path) -> tuple[Path, dict[str, Any]]:
    path = tex.with_suffix(".report.json")
    if not path.exists():
        raise CVForgeError(
            [
                Issue(
                    file=str(tex),
                    message=f"no {path.name} beside the .tex, so check cannot see what was built.",
                    fix="build it with `cvforge build ... -o` this path first; build writes both.",
                )
            ]
        )
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return path, data


def expected_facts(report: dict[str, Any]) -> list[Fact]:
    fields = set(report.get("template_fields", []))
    emitted = report["emitted"]
    facts: list[Fact] = []
    person = emitted["person"]
    for key in ("name", "email", "phone"):
        if f"person.{key}" in fields and person.get(key):
            facts.append(Fact("person", key, person[key]))
    title_field = {"experience": "title", "projects": "name", "education": "degree"}
    for item in emitted["items"]:
        sec = item["section"]
        checks = [
            (title_field[sec], item["title"]),
            ("org", item["org"]),
            ("start", item["start"]),
            ("end", item["end"]),
        ]
        for key, value in checks:
            if value and f"{sec}.{key}" in fields:
                facts.append(Fact(item["id"], key, value))
        for b in item["bullets"]:
            facts.append(Fact(b["id"], "bullet", " ".join(b["text"].split()[:8])))
    if fields & {"skills", "skill_groups.skills"}:
        facts.extend(Fact("skills", "skill", name) for name in emitted["skills"])
    return facts


def found_instead(text: str, expected: str) -> str | None:
    """What the parser returned where the fact should be: the closest span, or None."""
    want = squash(normalize(expected))
    if not want:
        return None
    gap = r"[\s\ufffd]{0,3}"
    pattern = gap.join(re.escape(ch) for ch in want.replace(" ", ""))
    m = re.search(pattern, text, flags=re.IGNORECASE)
    if m:
        start, end = m.start(), m.end()
        while start > 0 and not text[start - 1].isspace():  # include glued junk
            start -= 1
        while end < len(text) and not text[end].isspace():
            end += 1
        return text[start:end]
    words = text.split()
    n = len(want.split())
    best, best_ratio = None, 0.0
    for size in {max(1, n - 1), n, n + 1}:
        for i in range(0, max(1, len(words) - size + 1)):
            span = " ".join(words[i : i + size])
            ratio = SequenceMatcher(None, want.lower(), span.lower()).ratio()
            if ratio > best_ratio:
                best, best_ratio = span, ratio
    return best if best_ratio >= 0.6 else None


def judge(variants: list[str], expected: str, prefix: bool = False) -> str:
    """intact | glued | interleaved | missing, comparing case-insensitively.

    `prefix` marks a fact that is the start of a longer text (a bullet's first eight words).
    """
    want = squash(normalize(expected)).casefold()
    folded = [v.casefold() for v in variants]
    if any(contains_word(v, want) for v in folded):
        return "intact"
    if any(contains_glued(v, want, open_end=prefix) for v in folded):
        return "glued"
    if any(interleaved(v, want) for v in folded):
        return "interleaved"
    return "missing"


def roundtrip(
    parser: Parser,
    pdf: Path,
    facts: list[Fact],
    gate: bool,
    items: list[dict[str, Any]] | None = None,
) -> tuple[ParserResult, str]:
    reason = parser.unavailable()
    if reason:
        return ParserResult(parser.name, gate=gate, skipped=reason), ""
    raw = parser.extract(pdf)
    variants = extracted_variants(raw)
    result = ParserResult(parser.name, gate=gate, garbled=garbled_count(raw), checked=len(facts))
    for fact in facts:
        verdict = judge(variants, fact.expected, prefix=fact.field == "bullet")
        if verdict == "intact":
            continue
        found = found_instead(variants[1], fact.expected)
        if verdict == "glued":
            result.glued.append(Miss(fact, found, "glued"))
        elif verdict == "interleaved":
            result.misses.append(Miss(fact, found, "interleaved"))
        else:
            result.misses.append(Miss(fact, found, "garbled" if found else "lost"))
    result.dates_separated, result.dates_checked = dates_separated(raw, items or [])
    return result, raw


def resolve_parsers(
    settings: dict[str, ParserSetting], parsers: list[Parser] | None = None
) -> list[tuple[Parser, bool]]:
    """Adapters to run with their gate flag, applying cvforge.toml [parsers.*] overrides."""
    unknown = sorted(set(settings) - set(PARSER_NAMES))
    if unknown:
        raise CVForgeError(
            [
                Issue(
                    file="cvforge.toml",
                    message=f"[parsers] names unknown parser(s): {', '.join(unknown)}.",
                    fix=f"use one of: {', '.join(PARSER_NAMES)}.",
                )
            ]
        )
    chosen = []
    for parser in parsers or all_parsers():
        setting = settings.get(parser.name, ParserSetting())
        if not setting.enabled:
            continue
        gate = parser.default_gate if setting.gate is None else setting.gate
        chosen.append((parser, gate))
    return chosen


def page_count(pdf: Path) -> int | None:
    if shutil.which("pdfinfo") is None:
        return None
    out = subprocess.run(
        ["pdfinfo", str(pdf)], capture_output=True, text=True, check=False, timeout=30
    ).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, flags=re.MULTILINE)
    return int(m.group(1)) if m else None


def density(report: dict[str, Any], text: str, pages: int | None) -> dict[str, Any]:
    header = report.get("template_header", {})
    words = len(text.split())
    per_role = [
        len(i["bullets"]) for i in report["emitted"]["items"] if i["section"] == "experience"
    ]
    flags = []
    max_b, max_p = header.get("max_bullets_per_role"), header.get("max_pages")
    if max_b and per_role and max(per_role) > max_b:
        flags.append(f"a role has {max(per_role)} bullets; the template allows {max_b}")
    if max_p and pages and pages > max_p:
        flags.append(f"{pages} pages; the template allows {max_p}")
    wpp = round(words / pages) if pages else None
    if wpp is not None and wpp > 750:
        flags.append(f"{wpp} words per page reads as dense; consider fewer bullets")
    return {
        "pages": pages,
        "words": words,
        "words_per_page": wpp,
        "bullets_per_role": per_role,
        "flags": flags,
    }


def evidence_score(report: dict[str, Any]) -> float | None:
    skills = report["emitted"].get("skill_evidence", {})
    if not skills:
        return None
    backed = sum(1 for qids in skills.values() if qids)
    return round(backed / len(skills), 4)


def check(
    tex: Path,
    job: str | None,
    thresholds: Thresholds,
    *,
    strict: bool = False,
    lint_template: bool = False,
    semantic: bool = True,
    parsers: list[Parser] | None = None,
    settings: dict[str, ParserSetting] | None = None,
    encoder: Encoder | None = None,
) -> CheckReport:
    report_path, report = load_report(tex)
    chosen = resolve_parsers(settings or {}, parsers)
    template = Path(report.get("template", ""))
    pdf = compile_pdf(
        tex,
        engine=report.get("template_header", {}).get("engine") or "pdflatex",
        search=[template.parent] if template.is_file() else [],
    )
    facts = expected_facts(report)
    results: list[ParserResult] = []
    primary_text = ""
    for parser, gate in chosen:
        parsed, raw = roundtrip(parser, pdf, facts, gate, report["emitted"]["items"])
        results.append(parsed)
        if raw and gate and not primary_text:
            primary_text = raw
    warnings: list[Issue] = []
    for r in results:
        if r.glued:
            warnings.append(
                Issue(
                    file=str(pdf),
                    severity="warning",
                    message=f"{r.name} glued {len(r.glued)} fact(s) to neighbouring words "
                    f"(e.g. {r.glued[0].found!r}); the characters are intact.",
                    fix="usually tight word spacing or LuaLaTeX output; screening software "
                    "using this reader may miss those phrases.",
                )
            )
        if r.dates_separated:
            warnings.append(
                Issue(
                    file=str(pdf),
                    severity="warning",
                    message=f"{r.name} put {r.dates_separated} of {r.dates_checked} role dates "
                    "more than a line away from their title.",
                    fix="dates still came back; put them on the title line if you rely on "
                    "this reader linking dates to roles.",
                )
            )
        if r.skipped:
            warnings.append(
                Issue(
                    file=str(pdf),
                    severity="warning",
                    message=f"parser {r.name} skipped: {r.skipped}",
                    fix=r.skipped,
                )
            )
        elif r.garbled:
            warnings.append(
                Issue(
                    file=str(pdf),
                    severity="warning",
                    message=f"{r.name} found {r.garbled} unmappable glyph(s) (icons or symbols).",
                    fix="replace icons and symbol fonts with plain words.",
                )
            )
    scores: dict[str, Any] = {"keyword": None, "missing_terms": [], "semantic": None}
    if job and primary_text:
        scores["keyword"], scores["missing_terms"] = keyword_coverage(job, primary_text)
        if semantic:
            result_sem = semantic_similarity(job, primary_text, encoder)
            scores["semantic"] = result_sem.score
            if result_sem.score is None:
                scores["semantic_unavailable"] = result_sem.reason
                scores["semantic_fix"] = result_sem.fix
    scores["evidence"] = evidence_score(report)
    dens = density(report, primary_text, page_count(pdf))
    strict_failures: list[str] = []
    if strict:
        for key in ("keyword", "semantic", "evidence"):
            value, floor = scores.get(key), getattr(thresholds, key)
            if value is not None and value < floor:
                strict_failures.append(f"{key} {value:.2f} is below the threshold {floor:.2f}")
        strict_failures.extend(dens["flags"])
    result = CheckReport(
        tex=tex,
        pdf=pdf,
        parsers=results,
        scores=scores,
        density=dens,
        warnings=warnings,
        strict_failures=strict_failures,
        lint=lint(tex.read_text(encoding="utf-8"), str(tex)) if lint_template else [],
    )
    report["check"] = result.to_dict()
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def miss_issues(result: CheckReport) -> list[Issue]:
    """Gating misses are errors; advisory misses are warnings showing what came back."""
    issues = []
    for p in result.parsers:
        for m in p.misses:
            got = f"; it returned {m.found!r}" if m.found else "; nothing close came back"
            issues.append(
                Issue(
                    file=str(result.pdf),
                    item=m.fact.item,
                    severity="error" if p.gate else "warning",
                    message=f"{p.name}{'' if p.gate else ' (advisory)'} did not return the "
                    f"{m.fact.field} {m.fact.expected!r} as whole words ({m.kind}){got}.",
                    fix="look for icons, columns or symbols next to it in the template; "
                    "`cvforge template validate` lists parser-unsafe constructs."
                    if p.gate
                    else "advisory only: pipelines using this parser would read the text above.",
                )
            )
    return issues
