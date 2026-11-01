"""Terminal rendering of results with rich. Presentation only; no decisions are made here."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape
from rich.table import Table

if TYPE_CHECKING:
    from cvforge.check import CheckReport
    from cvforge.pipeline import ExplainResult
    from cvforge.rewrite import Proposal
    from cvforge.template import TemplateReport


def print_explain(console: Console, result: ExplainResult) -> None:
    sel = result.selection
    console.print(
        f"hat: {escape(result.hat or '(none, every skill weight 1)')}   "
        f"job: {escape(result.job or '(none)')}   "
        f"max bullets per role: {sel.max_bullets or 'no limit'}",
        highlight=False,
    )
    console.print("score = weight x hat x (1 + job)", style="dim")
    for si in sel.items():
        table = Table(title=f"{si.section}: {si.item.id}", title_justify="left", expand=True)
        table.add_column("id", no_wrap=True)
        table.add_column("score", justify="right")
        table.add_column("weight", justify="right")
        table.add_column("hat", justify="right")
        table.add_column("job", justify="right")
        table.add_column("text")
        for sb in si.bullets:
            p = sb.parts
            table.add_row(
                sb.qid,
                f"{sb.score:.2f}",
                f"{p['weight']:.0f}",
                f"{p['hat']:.2f}",
                f"{p['job']:.2f}",
                escape(sb.text),
            )
        if si.bullets:
            console.print(table)
    if sel.skills:
        console.print(
            "skills: " + ", ".join(f"{escape(s.name)} ({s.score:.1f})" for s in sel.skills),
            highlight=False,
        )
    if sel.dropped:
        dropped = Table(title="dropped", title_justify="left", expand=True)
        dropped.add_column("id", no_wrap=True)
        dropped.add_column("kind")
        dropped.add_column("reason")
        for d in sel.dropped:
            dropped.add_row(d.id, d.kind, escape(d.reason))
        console.print(dropped)
    n = len(sel.bullets())
    console.print(f"{n} bullets selected, {len(sel.dropped)} items dropped", highlight=False)


def print_template_report(console: Console, report: TemplateReport) -> None:
    if report.header is None:
        console.print(f"{report.file}: not a cvforge template", highlight=False)
        return
    h = report.header
    console.print(f"sections declared: {', '.join(h.sections) or '-'}", highlight=False)
    console.print(f"supports: {', '.join(h.supports) or '-'}", highlight=False)
    if report.will_fill or report.empty or report.left_out:
        console.print(f"will fill: {', '.join(report.will_fill) or '-'}", highlight=False)
        console.print(
            f"declared but empty in profile: {', '.join(report.empty) or '-'}", highlight=False
        )
        console.print(
            f"in profile but not in template: {', '.join(report.left_out) or '-'}", highlight=False
        )
    console.print(f"filled fields: {', '.join(report.fields) or '-'}", highlight=False)
    if report.fixed_text:
        console.print("fixed text (printed as written, never filled):", highlight=False)
        for line, text in report.fixed_text:
            console.print(f"  line {line}: {escape(text)}", highlight=False)
    else:
        console.print("fixed text: none", highlight=False)
    status = "valid" if report.ok else "invalid"
    lint = f", {len(report.lint)} parser-safety warning(s)" if report.lint else ""
    console.print(f"{report.file}: {status}{lint}", highlight=False)


def print_check(console: Console, result: CheckReport) -> None:
    for p in result.parsers:
        role = "gate" if p.gate else "advisory"
        if p.skipped:
            status = f"skipped ({escape(p.skipped)})"
        elif p.ok:
            status = f"ok, {p.checked} facts returned"
        else:
            verdict = "FAILED" if p.gate else "warning"
            status = f"{verdict}, {len(p.misses)} of {p.checked} facts lost"
        console.print(f"{p.name} [{role}]: {status}", highlight=False, markup=False)
    s = result.scores
    if s.get("keyword") is not None:
        console.print(f"keyword coverage: {s['keyword']:.2f}", highlight=False)
        if s.get("missing_terms"):
            console.print(
                "job terms not in the CV: " + escape(", ".join(s["missing_terms"])),
                highlight=False,
            )
    if s.get("semantic") is not None:
        console.print(f"semantic similarity: {s['semantic']:.2f}", highlight=False)
    elif s.get("semantic_unavailable"):
        console.print(
            f"semantic: unavailable: {escape(s['semantic_unavailable'])} "
            f"To enable: {escape(s['semantic_fix'])}",
            highlight=False,
            soft_wrap=True,
        )
    if s.get("evidence") is not None:
        console.print(f"evidence: {s['evidence']:.0%} of skills shown are backed by a bullet")
    d = result.density
    console.print(
        f"density: {d['pages']} page(s), {d['words']} words, "
        f"bullets per role {d['bullets_per_role']}",
        highlight=False,
    )
    for flag in d["flags"]:
        console.print(f"  note: {escape(flag)}", highlight=False)
    for failure in result.strict_failures:
        console.print(f"strict: {escape(failure)}", style="red", highlight=False)
    verdict = "passed" if result.ok else "failed"
    console.print(f"check {verdict}: {result.badge}", highlight=False)


def print_proposals(console: Console, proposals: list[Proposal]) -> None:
    changed = [p for p in proposals if p.status != "unchanged"]
    if not changed:
        console.print("the model proposed no changes", highlight=False)
        return
    table = Table(title="proposed rewrites", title_justify="left", expand=True, show_lines=True)
    table.add_column("id", no_wrap=True)
    table.add_column("before")
    table.add_column("after")
    table.add_column("fact check")
    for p in changed:
        verdict = (
            "[red]rejected: adds " + escape(", ".join(p.new_facts)) + "[/red]"
            if p.status == "auto-rejected"
            else "[green]ok[/green]"
        )
        table.add_row(p.qid, escape(p.original), escape(p.rewritten), verdict)
    console.print(table)
