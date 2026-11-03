"""cv-check.yml writes the summary line and the reader table to the Actions step summary."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from ruamel.yaml import YAML

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "cv-check.yml"


def _summary_script() -> str:
    steps = YAML(typ="safe").load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["cv"]["steps"]
    run = next(s["run"] for s in steps if s.get("id") == "check")
    m = re.search(r"python - <<'PY'\n(.*?)\nPY\n", run, re.S)
    assert m, "the check step lost its Python summary block"
    return m.group(1)


def _run(tmp_path: Path, report: dict[str, object] | None) -> tuple[str, str]:
    if report is not None:
        (tmp_path / "check.json").write_text(json.dumps(report), encoding="utf-8")
    summary, output = tmp_path / "summary.md", tmp_path / "output.txt"
    subprocess.run(
        [sys.executable, "-c", _summary_script()],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        encoding="utf-8",
        env={"GITHUB_STEP_SUMMARY": str(summary), "GITHUB_OUTPUT": str(output)},
    )
    return summary.read_text(encoding="utf-8"), output.read_text(encoding="utf-8")


def _reader(name: str, gate: bool, **kw: object) -> dict[str, object]:
    base: dict[str, object] = {"name": name, "gate": gate, "ok": True, "skipped": None}
    base |= {"checked": 40, "misses": []}
    return base | kw


REPORT = {
    "ok": False,
    "badge": "parsed: 2/3 · evidence: 100%",
    "gates": ["pdfplumber", "pypdf-layout", "pdfium"],
    "parsers": [
        _reader("pdfplumber", True),
        _reader("pypdf-layout", True),
        _reader(
            "pdfium",
            True,
            ok=False,
            misses=[{"item": "exp-01.b2", "field": "bullet", "expected": "Cut | costs"}],
        ),
        _reader("pdftotext", False, ok=False, skipped="not installed (poppler); install: x"),
    ],
    "warnings": [{"severity": "warning", "message": "a note.", "fix": "do y."}],
    "lint": [],
    "strict_failures": [],
}


def test_summary_has_verdict_line_and_reader_table(tmp_path: Path) -> None:
    summary, output = _run(tmp_path, REPORT)
    assert "**check failed:** `parsed: 2/3 · evidence: 100%`" in summary
    assert "Gating readers on this system: pdfplumber, pypdf-layout, pdfium" in summary
    assert "| Reader | Role | Result |" in summary
    assert "| pdfplumber | gate | ok, 40 facts returned |" in summary
    assert "| pdfium | gate | FAILED, 1 of 40 facts lost |" in summary
    assert "| pdftotext | advisory | skipped (not installed (poppler); install: x) |" in summary
    assert "- pdfium: lost bullet `Cut | costs` (exp-01.b2)" in summary
    assert "- warning: a note. Fix: do y." in summary
    assert output == "badge=parsed: 2/3 · evidence: 100%\n"


def test_summary_passed(tmp_path: Path) -> None:
    report = REPORT | {"ok": True, "badge": "parsed: 3/3", "parsers": [_reader("pdfium", True)]}
    summary, _ = _run(tmp_path, report)
    assert "**check passed:** `parsed: 3/3`" in summary


def test_summary_without_a_report_says_so(tmp_path: Path) -> None:
    summary, output = _run(tmp_path, None)
    assert "**check failed:** cvforge check wrote no JSON report" in summary
    assert output == "badge=check error\n"
