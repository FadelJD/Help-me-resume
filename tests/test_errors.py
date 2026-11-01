"""Every bad fixture's error names where, a line or item id, and a one-line fix."""

from __future__ import annotations

import pytest

from .errors_audit import DOC, LINE, Outcome, document, run_all

RESULTS = run_all()


@pytest.mark.parametrize("outcome", RESULTS, ids=[f"{r.case.kind}:{r.case.name}" for r in RESULTS])
def test_message_names_file_location_and_fix(outcome: Outcome) -> None:
    assert outcome.exit_code != 0, f"{outcome.case.argv} should fail"
    assert outcome.lines, f"{outcome.case.argv} printed no error"
    for line in outcome.lines:
        m = LINE.match(line)
        assert m, f"not in 'where[:line] [item]: error: message Fix: fix' form: {line}"
        assert m["line"] or m["item"], f"no line number or item id: {line}"
        assert len(m["fix"].split()) >= 3, f"fix too short to act on: {line}"
        if outcome.case.target:
            assert m["where"] == outcome.case.target, line
        else:
            assert m["where"], line


def test_every_kind_is_covered() -> None:
    kinds = {r.case.kind for r in RESULTS}
    assert kinds == {"profile", "hat", "template", "command"}
    assert sum(r.case.kind == "command" for r in RESULTS) >= 10


def test_errors_doc_is_current() -> None:
    assert DOC.read_text(encoding="utf-8") == document(RESULTS), (
        "docs/errors.md is stale; run `python -m tests.errors_audit --write`"
    )
