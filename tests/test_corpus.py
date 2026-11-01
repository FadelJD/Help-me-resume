"""The published parser table must match what the parsers return today.

Regenerate after an intended change with: python -m tests.corpus --write
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cvforge.template import validate_template

from .corpus import CORPUS, RESULTS, manifest, missing_requirements, run_template

ENTRIES = manifest()
SNAPSHOT: dict[str, Any] = {r["name"]: r for r in json.loads(RESULTS.read_text())}


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "roundtrip_ok": result["roundtrip_ok"],
        "parsers": {
            name: {
                "ok": p["ok"],
                "misses": sorted((m["item"], m["field"], m["kind"]) for m in p["misses"]),
            }
            for name, p in result["parsers"].items()
        },
    }


@pytest.mark.parametrize("entry", ENTRIES, ids=[e["name"] for e in ENTRIES])
def test_corpus_template_has_licence_original_and_valid_contract(entry: dict[str, Any]) -> None:
    folder = CORPUS / entry["name"]
    assert (folder / "original").is_dir()
    assert any((folder / n).exists() for n in ("LICENSE", "LICENCE", "LICENSE-NOTE.md"))
    _, report = validate_template(folder / "template.tex", None)
    assert report.ok, [str(i) for i in report.issues]


@pytest.mark.tex
@pytest.mark.corpus
@pytest.mark.parametrize("entry", ENTRIES, ids=[e["name"] for e in ENTRIES])
def test_corpus_matches_published_table(entry: dict[str, Any], tmp_path: Path) -> None:
    missing = missing_requirements(entry)
    if missing:
        pytest.skip(f"needs {', '.join(missing)}; run tests/fixtures/templates/provision.sh")
    fresh = _summary(run_template(entry, tmp_path))
    published = _summary(SNAPSHOT[entry["name"]])
    assert fresh == published, (
        "parser results differ from docs/parser-table.md; if the change is intended, run "
        "`python -m tests.corpus --write` and say why in the commit message"
    )
