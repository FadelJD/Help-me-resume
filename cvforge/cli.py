"""Typer app. Thin: parses flags, calls the pipeline, prints one line, sets the exit code."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.markup import escape

from cvforge import pipeline, views
from cvforge.check import miss_issues
from cvforge.errors import CVForgeError, Issue
from cvforge.rewrite import Proposal

app = typer.Typer(no_args_is_help=True, add_completion=False)
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
def tailor(
    job: Annotated[str, typer.Option("--job", help="Job ad: a text file or an http(s) URL.")],
    template: TemplateOpt = None,
    hat: HatOpt = None,
    rewrite: Annotated[
        bool, typer.Option("--rewrite", help="Offer LLM rewording; every change needs approval.")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Accept every rewrite that passed the fact check.")
    ] = False,
    output: Annotated[Path | None, typer.Option("-o", "--output", help="Output .tex path.")] = None,
    compile_pdf: Annotated[bool, typer.Option("--compile", help="Also build the PDF.")] = False,
    max_bullets: MaxOpt = None,
    locale: LocaleOpt = None,
    profile: ProfileOpt = None,
    as_json: JsonOpt = False,
) -> None:
    """Build against a job ad, optionally with LLM rewording you approve bullet by bullet."""

    def approve(proposals: list[Proposal]) -> None:
        views.print_proposals(console, proposals)
        valid = [p for p in proposals if p.valid]
        if not valid:
            return
        if yes:
            choice = "a"
        elif as_json or not sys.stdin.isatty():
            choice = "r"
        else:
            choice = (
                typer.prompt(
                    f"{len(valid)} rewrite(s) passed the fact check: "
                    "[a]ccept all, [p]ick, [r]eject all",
                    default="p",
                )
                .strip()
                .lower()[:1]
            )
        for p in valid:
            if choice == "a":
                p.status = "accepted"
            elif choice == "p":
                accept = typer.confirm(f"Use the rewrite for {p.qid}?", default=True)
                p.status = "accepted" if accept else "rejected"
            else:
                p.status = "rejected"

    try:
        _apply_locale(locale)
        result, proposals = pipeline.tailor(
            profile=profile,
            template=template,
            hat=hat,
            job=job,
            output=output,
            max_bullets=max_bullets,
            compile_pdf_too=compile_pdf,
            rewrite=rewrite,
            approve=approve,
        )
    except CVForgeError as exc:
        _fail(exc, as_json)
    accepted = sum(1 for p in proposals if p.status == "accepted")
    if as_json:
        out.print_json(
            json.dumps(
                {
                    "ok": True,
                    "tex": str(result.tex),
                    "pdf": str(result.pdf) if result.pdf else None,
                    "report": str(result.report_path),
                    "rewrites": [p.to_dict() for p in proposals],
                }
            )
        )
        return
    _print_issues(result.warnings)
    tail = f", {accepted} rewrite(s) applied" if rewrite else ""
    out.print(result.summary + tail, highlight=False, soft_wrap=True)


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


@app.command("check")
def check_cmd(
    tex: Annotated[Path, typer.Argument(help="A .tex written by build (its report.json too).")],
    job: JobOpt = None,
    strict: Annotated[
        bool, typer.Option("--strict", help="Also fail on scores below cvforge.toml thresholds.")
    ] = False,
    lint_template: Annotated[
        bool, typer.Option("--lint-template", help="Show parser-safety warnings for the layout.")
    ] = False,
    semantic: Annotated[
        bool, typer.Option("--semantic/--no-semantic", help="Embedding score if installed.")
    ] = True,
    as_json: JsonOpt = False,
) -> None:
    """Compile, extract with real parsers, and fail on any fact that did not come back."""
    try:
        result = pipeline.run_check(
            tex, job, strict=strict, lint_template=lint_template, semantic=semantic
        )
    except CVForgeError as exc:
        _fail(exc, as_json)
    if as_json:
        out.print_json(json.dumps(result.to_dict()))
    else:
        _print_issues(miss_issues(result) + result.warnings + result.lint)
        views.print_check(out, result)
    if not result.ok:
        raise typer.Exit(1)


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


@app.command()
def init(
    force: Annotated[bool, typer.Option("--force", help="Overwrite existing files.")] = False,
    defaults: Annotated[
        bool, typer.Option("--defaults", help="Accept every default without asking.")
    ] = False,
) -> None:
    """Interview: writes profile.cv.txt, cvforge.toml and starter hats in this folder."""

    def ask(prompt: str, default: str) -> str:
        if defaults:
            return default
        return str(typer.prompt(prompt, default=default, show_default=bool(default)))

    def confirm(prompt: str, default: bool) -> bool:
        return False if defaults else typer.confirm(prompt, default=default)

    def say(message: str) -> None:
        if not defaults:
            console.print(escape(message), highlight=False)

    try:
        result = pipeline.init(ask, confirm, say, force=force)
    except CVForgeError as exc:
        _fail(exc, False)
    out.print(result.path.read_text(encoding="utf-8"), highlight=False, markup=False)
    out.print(result.message, highlight=False, soft_wrap=True)


add_app = typer.Typer(no_args_is_help=True, help="Append to the profile without opening it.")
app.add_typer(add_app, name="add")


def _report_write(fn: Callable[[], pipeline.WriteResult]) -> None:
    try:
        result = fn()
    except CVForgeError as exc:
        _fail(exc, False)
    out.print(result.message, highlight=False, soft_wrap=True)


def _csv(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


@add_app.command("skill")
def add_skill(
    skill_id: Annotated[str, typer.Argument(help="Short id bullets will reference, e.g. rust.")],
    name: Annotated[str, typer.Argument(help="Name as shown on the CV, e.g. Rust.")],
    profile: ProfileOpt = None,
) -> None:
    """Declare a skill."""
    _report_write(lambda: pipeline.add_skill(profile, skill_id, name))


@add_app.command("role")
def add_role(
    title: Annotated[str, typer.Argument(help="Job title.")],
    org: Annotated[str, typer.Option("--org", help="Employer.")],
    start: Annotated[str, typer.Option("--start", help="YYYY-MM.")],
    end: Annotated[str, typer.Option("--end", help="YYYY-MM or present.")] = "present",
    location: Annotated[str | None, typer.Option("--location")] = None,
    tags: Annotated[str, typer.Option("--tags", help="Skill ids, comma separated.")] = "",
    item_id: Annotated[str | None, typer.Option("--id", help="Default: next exp-NN.")] = None,
    profile: ProfileOpt = None,
) -> None:
    """Add a role to experience."""
    _report_write(
        lambda: pipeline.add_role(
            profile,
            title=title,
            org=org,
            start=start,
            end=end,
            location=location,
            tags=_csv(tags),
            item_id=item_id,
        )
    )


@add_app.command("bullet")
def add_bullet(
    item: Annotated[str, typer.Argument(help="Role, project or education id, e.g. exp-02.")],
    text: Annotated[str, typer.Argument(help="One line: what you did and the result.")],
    skills: Annotated[str, typer.Option("--skills", help="Skill ids, comma separated.")] = "",
    weight: Annotated[int, typer.Option("--weight", min=1, max=5, help="1-5.")] = 3,
    bullet_id: Annotated[str | None, typer.Option("--id", help="Default: next bN.")] = None,
    profile: ProfileOpt = None,
) -> None:
    """Add a bullet to a role, project or education entry."""
    _report_write(
        lambda: pipeline.add_bullet(
            profile,
            item_id=item,
            text_=text,
            skills=_csv(skills),
            weight=weight,
            bullet_id=bullet_id,
        )
    )


@add_app.command("project")
def add_project(
    name: Annotated[str, typer.Argument(help="Project name.")],
    url: Annotated[str | None, typer.Option("--url")] = None,
    item_id: Annotated[str | None, typer.Option("--id", help="Default: next prj-NN.")] = None,
    profile: ProfileOpt = None,
) -> None:
    """Add a project."""
    _report_write(lambda: pipeline.add_project(profile, name=name, url=url, item_id=item_id))


@add_app.command("education")
def add_education(
    degree: Annotated[str, typer.Argument(help="Degree or certificate.")],
    org: Annotated[str, typer.Option("--org", help="Institution.")],
    end: Annotated[str, typer.Option("--end", help="YYYY-MM or present.")],
    start: Annotated[str | None, typer.Option("--start", help="YYYY-MM.")] = None,
    item_id: Annotated[str | None, typer.Option("--id", help="Default: next edu-NN.")] = None,
    profile: ProfileOpt = None,
) -> None:
    """Add an education entry."""
    _report_write(
        lambda: pipeline.add_education(
            profile, degree=degree, org=org, start=start, end=end, item_id=item_id
        )
    )
