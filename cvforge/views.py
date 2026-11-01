"""Terminal rendering of results with rich. Presentation only; no decisions are made here."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.markup import escape
from rich.table import Table

if TYPE_CHECKING:
    from cvforge.pipeline import ExplainResult
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
    status = "valid" if report.ok else "invalid"
    lint = f", {len(report.lint)} parser-safety warning(s)" if report.lint else ""
    console.print(f"{report.file}: {status}{lint}", highlight=False)
