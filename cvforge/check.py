"""Compile, extract with real parsers, assert every emitted fact came back, score -> Report.

The round-trip needs no model: for each parser it asserts that the name, contact details, every
title, org and date, the first eight words of every bullet, and every skill name survive
extraction as whole words. A fact glued to junk (an icon glyph, a neighbouring word) counts as
lost, because a parser reading that text gets the wrong value.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cvforge.compile import compile_pdf
from cvforge.config import Thresholds
from cvforge.errors import CVForgeError, Issue
from cvforge.parsers import Parser, all_parsers
from cvforge.score import keyword_coverage, semantic_similarity
from cvforge.template import lint

_CHARMAP = str.maketrans(
    {
        **dict.fromkeys([0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212], "-"),  # dashes
        **dict.fromkeys([0x2018, 0x2019], "'"),  # curly single quotes
        **dict.fromkeys([0x201C, 0x201D], '"'),  # curly double quotes
        0x02DC: "~",  # small tilde
        0x00A0: " ",  # no-break space
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
    """Two readings of line-end hyphens: a soft hyphen (join) or a real one (keep)."""
    text = normalize(raw)
    joined = re.sub(r"-\n(?=[a-z])", "", text)
    kept = re.sub(r"-\n", "-", text)
    return [squash(joined), squash(kept)]


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


def garbled_count(raw: str) -> int:
    text = _CID.sub(JUNK, raw)
    return sum(1 for ch in text if _is_junk(ch) and ch not in "\n\r\t\f")


@dataclass(frozen=True)
class Fact:
    item: str
    field: str
    expected: str


@dataclass
class ParserResult:
    name: str
    skipped: str | None = None
    misses: list[Fact] = field(default_factory=list)
    garbled: int = 0
    checked: int = 0

    @property
    def ok(self) -> bool:
        return self.skipped is None and not self.misses


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
    def roundtrip_ok(self) -> bool:
        ran = [p for p in self.parsers if p.skipped is None]
        return bool(ran) and all(p.ok for p in ran)

    @property
    def ok(self) -> bool:
        return self.roundtrip_ok and not self.strict_failures

    @property
    def badge(self) -> str:
        ran = [p for p in self.parsers if p.skipped is None]
        parts = [f"parsed: {sum(p.ok for p in ran)}/{len(ran)}"]
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
                    "ok": p.ok,
                    "skipped": p.skipped,
                    "checked": p.checked,
                    "garbled_glyphs": p.garbled,
                    "misses": [
                        {"item": m.item, "field": m.field, "expected": m.expected} for m in p.misses
                    ],
                }
                for p in self.parsers
            ],
            "scores": self.scores,
            "density": self.density,
            "strict_failures": self.strict_failures,
            "warnings": [w.to_dict() for w in self.warnings],
            "lint": [i.to_dict() for i in self.lint],
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


def roundtrip(parser: Parser, pdf: Path, facts: list[Fact]) -> tuple[ParserResult, str]:
    reason = parser.unavailable()
    if reason:
        return ParserResult(parser.name, skipped=reason), ""
    raw = parser.extract(pdf)
    variants = extracted_variants(raw)
    result = ParserResult(parser.name, garbled=garbled_count(raw), checked=len(facts))
    for fact in facts:
        want = squash(normalize(fact.expected))
        if not any(contains_word(v, want) for v in variants):
            result.misses.append(fact)
    return result, raw


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
) -> CheckReport:
    report_path, report = load_report(tex)
    pdf = compile_pdf(tex)
    facts = expected_facts(report)
    results: list[ParserResult] = []
    primary_text = ""
    for parser in parsers or all_parsers():
        parsed, raw = roundtrip(parser, pdf, facts)
        results.append(parsed)
        if raw and not primary_text:
            primary_text = raw
    warnings: list[Issue] = []
    for r in results:
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
            scores["semantic"] = semantic_similarity(job, primary_text)
            if scores["semantic"] is None:
                scores["semantic_note"] = "install cvforge[semantic] for the embedding score"
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
    issues = []
    for p in result.parsers:
        for m in p.misses:
            issues.append(
                Issue(
                    file=str(result.pdf),
                    item=m.item,
                    message=f"{p.name} did not return the {m.field} {m.expected!r} as whole words.",
                    fix="look for icons, columns or symbols next to it in the template; "
                    "`cvforge template validate` lists parser-unsafe constructs.",
                )
            )
    return issues
