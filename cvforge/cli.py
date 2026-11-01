"""Typer app. Thin: parses flags, calls the pipeline, prints one line, sets the exit code."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.markup import escape

from cvforge import pipeline, views
from cvforge.errors import CVForgeError, Issue

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)
console = Console(stderr=True)
out = Console()

JsonOpt = Annotated[bool, typer.Option("--json", help="Machine-readable output on stdout.")]
ProfileOpt = Annotated[
    Path | None, typer.Option("--profile", "-p", help="Profile file (default from cvforge.toml).")
]


@app.callback()
def _root() -> None:
    """CV Forge: plain-text profile in, screened LaTeX CV out. Every command works offline."""


def _print_issues(issues: list[Issue]) -> None:
    for issue in issues:
        style = "red" if issue.severity == "error" else "yellow"
        console.print(f"[{style}]{escape(str(issue))}[/{style}]", highlight=False, soft_wrap=True)


def _fail(exc: CVForgeError, as_json: bool) -> NoReturn:
    if as_json:
        out.print_json(json.dumps({"ok": False, "issues": [i.to_dict() for i in exc.issues]}))
    else:
        _print_issues(exc.issues)
        n = len(exc.issues)
        console.print(f"[red]failed: {n} problem{'s' if n != 1 else ''}[/red]")
    raise typer.Exit(1)


@app.command()
def validate(profile: ProfileOpt = None, as_json: JsonOpt = False) -> None:
    """Check the profile: schema, ids, skill references, dates."""
    try:
        result = pipeline.validate(profile)
    except CVForgeError as exc:
        _fail(exc, as_json)
    if as_json:
        out.print_json(json.dumps(result.to_dict()))
    else:
        _print_issues(result.issues)
        out.print(result.summary, highlight=False, soft_wrap=True)
    if not result.ok:
        raise typer.Exit(1)


def main() -> None:  # pragma: no cover
    sys.exit(app())


TemplateOpt = Annotated[
    Path | None,
    typer.Option("--template", "-t", help="LaTeX template (default from cvforge.toml)."),
]
HatOpt = Annotated[str | None, typer.Option("--hat", help="Hat name in hats/, or a .toml path.")]
JobOpt = Annotated[str | None, typer.Option("--job", help="Job ad: a text file or an http(s) URL.")]
MaxOpt = Annotated[
    int | None,
    typer.Option("--max-bullets", min=1, help="Lower the template's bullets-per-role limit."),
]
LocaleOpt = Annotated[
    str | None, typer.Option("--locale", help="au | uk | us | th (default from cvforge.toml).")
]


def _apply_locale(locale: str | None) -> None:
    if locale is not None:
        pipeline.override_locale(locale)


@app.command()
def build(
    template: TemplateOpt = None,
    hat: HatOpt = None,
    job: JobOpt = None,
    output: Annotated[Path | None, typer.Option("-o", "--output", help="Output .tex path.")] = None,
    compile_pdf: Annotated[bool, typer.Option("--compile", help="Also build the PDF.")] = False,
    max_bullets: MaxOpt = None,
    locale: LocaleOpt = None,
    profile: ProfileOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Render the profile into the template: profile in, .tex out, no network."""
    try:
        _apply_locale(locale)
        result = pipeline.build(
            profile=profile,
            template=template,
            hat=hat,
            job=job,
            output=output,
            max_bullets=max_bullets,
            compile_pdf_too=compile_pdf,
        )
    except CVForgeError as exc:
        _fail(exc, as_json)
    if as_json:
        out.print_json(
            json.dumps(
                {
                    "ok": True,
                    "tex": str(result.tex),
                    "pdf": str(result.pdf) if result.pdf else None,
                    "report": str(result.report_path),
                }
            )
        )
        return
    _print_issues(result.warnings)
    out.print(result.summary, highlight=False, soft_wrap=True)


@app.command()
def explain(
    template: TemplateOpt = None,
    hat: HatOpt = None,
    job: JobOpt = None,
    max_bullets: MaxOpt = None,
    profile: ProfileOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Show what a build would choose and why, without writing anything."""
    try:
        result = pipeline.explain(
            profile=profile, template=template, hat=hat, job=job, max_bullets=max_bullets
        )
    except CVForgeError as exc:
        _fail(exc, as_json)
    if as_json:
        out.print_json(json.dumps(result.to_dict()))
        return
    views.print_explain(out, result)


template_app = typer.Typer(no_args_is_help=True, help="Work with LaTeX templates.")
app.add_typer(template_app, name="template")


@template_app.command("validate")
def template_validate(
    template: Annotated[Path, typer.Argument(help="The .tex template to check.")],
    profile: ProfileOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Check the template contract and lint it for parser-unsafe layout."""
    try:
        report = pipeline.template_validate(template, profile)
    except CVForgeError as exc:
        _fail(exc, as_json)
    if as_json:
        out.print_json(json.dumps(report.to_dict()))
    else:
        _print_issues(report.issues + report.lint)
        views.print_template_report(out, report)
    if not report.ok:
        raise typer.Exit(1)
