"""Typer app. Thin: parses flags, calls the pipeline, prints one line, sets the exit code."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.markup import escape

from cvforge import pipeline
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
        out.print(result.summary, highlight=False)
    if not result.ok:
        raise typer.Exit(1)


def main() -> None:  # pragma: no cover
    sys.exit(app())
