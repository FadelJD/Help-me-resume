"""Template corpus runner: build every corpus template with the sample profile, run every parser.

    python -m tests.corpus            # print the Markdown table
    python -m tests.corpus --write    # also write docs/parser-table.md and results.json

tests/test_corpus.py compares a fresh run with the committed results.json, so the published
table cannot drift from what the parsers actually return.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

from cvforge import pipeline
from cvforge.check import check
from cvforge.config import Thresholds
from cvforge.parsers import PARSER_NAMES
from cvforge.template import lint

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "fixtures" / "templates"
RESULTS = CORPUS / "results.json"
TABLE = ROOT / "docs" / "parser-table.md"
PROFILE = ROOT / "examples" / "profile.cv.txt"
HAT = ROOT / "examples" / "hats" / "full-stack-engineer.toml"


def manifest() -> list[dict[str, Any]]:
    data = tomllib.loads((CORPUS / "corpus.toml").read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = data["template"]
    return entries


def missing_requirements(entry: dict[str, Any]) -> list[str]:
    missing = []
    for req in entry.get("requires", []):
        kind, _, value = req.partition(":")
        if kind == "cmd" and shutil.which(value) is None:
            missing.append(req)
        elif kind == "sty":
            found = subprocess.run(
                ["kpsewhich", value], capture_output=True, encoding="utf-8", errors="replace"
            ).stdout
            if not found.strip():
                missing.append(req)
        elif kind == "font" and shutil.which("fc-list"):
            fonts = subprocess.run(
                ["fc-list", ":", "family"], capture_output=True, encoding="utf-8", errors="replace"
            )
            if value not in fonts.stdout:
                missing.append(req)
    return missing


def run_template(entry: dict[str, Any], workdir: Path) -> dict[str, Any]:
    template = CORPUS / entry["name"] / "template.tex"
    out = workdir / entry["name"] / f"{entry['name']}.tex"
    pipeline.build(
        profile=PROFILE,
        template=template,
        hat=str(HAT),
        job=None,
        output=out,
        max_bullets=None,
        compile_pdf_too=False,
    )
    result = check(out, None, Thresholds(), semantic=False)
    parsers = {}
    for p in result.parsers:
        parsers[p.name] = {
            "gate": p.gate,
            "ok": p.ok,
            "checked": p.checked,
            "garbled_glyphs": p.garbled,
            "dates_separated": p.dates_separated,
            "dates_checked": p.dates_checked,
            "misses": [
                {
                    "item": m.fact.item,
                    "field": m.fact.field,
                    "kind": m.kind,
                    "expected": m.fact.expected,
                    "found": m.found,
                }
                for m in p.misses
            ],
            "glued": len(p.glued),
        }
    return {
        "name": entry["name"],
        "roundtrip_ok": result.roundtrip_ok,
        "lint": sorted({i.message.split(":")[0] for i in lint(template.read_text(), "t")}),
        "parsers": parsers,
    }


def cell(p: dict[str, Any]) -> str:
    notes = []
    if p["glued"]:
        notes.append(f"glued {p['glued']}")
    if p["dates_separated"]:
        notes.append(f"dates apart {p['dates_separated']}/{p['dates_checked']}")
    if not p["misses"]:
        return "✓" + (f" ({', '.join(notes)})" if notes else "")
    shown = []
    for m in p["misses"][:2]:
        got = "nothing close" if not m["found"] else f"`{m['found'][:28]}`"
        shown.append(f"{m['field']} `{m['expected'][:24]}` → {got}")
    more = len(p["misses"]) - len(shown)
    kinds = sorted({m["kind"] for m in p["misses"]})
    text = f"✗ {len(p['misses'])} {'/'.join(kinds)}: " + "; ".join(shown)
    if more > 0:
        text += f"; +{more} more"
    if notes:
        text += f" ({', '.join(notes)})"
    return text.replace("|", "\\|")


def table(results: list[dict[str, Any]]) -> str:
    entries = {e["name"]: e for e in manifest()}
    gates = results[0]["parsers"] if results else {}
    head = ["Template"] + [
        f"{name} ({'gate' if gates.get(name, {}).get('gate') else 'advisory'})"
        for name in PARSER_NAMES
    ]
    lines = ["| " + " | ".join(head) + " |", "|" + " --- |" * len(head)]
    for r in results:
        e = entries[r["name"]]
        row = [f"[{e['title']}]({e['source']})"]
        row += [
            cell(r["parsers"][name]) if name in r["parsers"] else "skipped" for name in PARSER_NAMES
        ]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def document(results: list[dict[str, Any]]) -> str:
    entries = {e["name"]: e for e in manifest()}
    parts = [
        "# Parser table",
        "",
        "Every corpus template built with `examples/profile.cv.txt` and the",
        "`full-stack-engineer` hat, compiled, and read back by every parser adapter. Generated",
        "by `python -m tests.corpus --write`; `tests/test_corpus.py` fails if a fresh run",
        "disagrees with this table.",
        "",
        "Gate and advisory labels are the Linux and macOS defaults. On Windows, where poppler",
        "is not installed by default, pdfplumber, pypdf-layout and pdfium gate and pdftotext is",
        "advisory when present; the pdfium column shows how that reader behaves.",
        "",
        "✓ means every fact came back as whole words. ✗ lists what was lost: *garbled* (something",
        "close came back), *interleaved* (the words came back with other text between them, i.e.",
        "merged columns) or *lost*. *glued N* counts facts that came back with inter-word spaces",
        "missing; *dates apart* counts role dates more than a line away from their title. Both",
        "are warnings, not failures.",
        "",
        table(results),
        "## Templates",
        "",
        "| Template | Licence | Layout | Lint warnings |",
        "| --- | --- | --- | --- |",
    ]
    for r in results:
        e = entries[r["name"]]
        lint_text = "; ".join(r["lint"]) or "none"
        parts.append(f"| {e['title']} | {e['licence']} | {e['layout']} | {lint_text} |")
    return "\n".join(parts) + "\n"


def run_all(workdir: Path) -> list[dict[str, Any]]:
    results = []
    for entry in manifest():
        missing = missing_requirements(entry)
        if missing:
            print(f"skip {entry['name']}: missing {', '.join(missing)}", file=sys.stderr)
            continue
        results.append(run_template(entry, workdir))
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--workdir", type=Path, default=ROOT / "out" / "corpus")
    args = ap.parse_args()
    results = run_all(args.workdir)
    if args.write:
        RESULTS.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
        TABLE.write_text(document(results), encoding="utf-8")
    print(table(results))


if __name__ == "__main__":
    main()
