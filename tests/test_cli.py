from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cvforge.cli import app

from .conftest import EXAMPLES, FIXTURES, TEMPLATES

runner = CliRunner()


@pytest.fixture(autouse=True)
def _cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def test_validate_ok() -> None:
    r = runner.invoke(app, ["validate", "-p", str(EXAMPLES / "profile.cv.txt")])
    assert r.exit_code == 0
    assert "valid (2 roles, 13 bullets, 11 skills)" in r.stdout


def test_validate_bad_exits_nonzero_and_names_line() -> None:
    r = runner.invoke(app, ["validate", "-p", str(FIXTURES / "profile_bad_skill_ref.cv.txt")])
    assert r.exit_code == 1
    assert "profile_bad_skill_ref.cv.txt:20" in r.stderr


def test_validate_json() -> None:
    r = runner.invoke(app, ["validate", "--json", "-p", str(FIXTURES / "profile_bad_date.cv.txt")])
    assert r.exit_code == 1
    data = json.loads(r.stdout)
    assert data["ok"] is False and data["issues"][0]["line"] == 11


def test_template_validate() -> None:
    r = runner.invoke(app, ["template", "validate", str(TEMPLATES / "minimal.tex")])
    assert r.exit_code == 0 and "valid" in r.stdout
    r = runner.invoke(app, ["template", "validate", str(FIXTURES / "template_noid.tex")])
    assert r.exit_code == 1


def test_build_and_explain(tmp_path: Path) -> None:
    common = [
        "-p",
        str(EXAMPLES / "profile.cv.txt"),
        "--hat",
        str(EXAMPLES / "hats" / "developer.toml"),
        "--job",
        str(FIXTURES / "job_backend.txt"),
    ]
    r = runner.invoke(
        app, ["build", "-t", str(TEMPLATES / "minimal.tex"), "-o", "out/x.tex", "--json", *common]
    )
    assert r.exit_code == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["tex"] == "out/x.tex"
    r = runner.invoke(app, ["explain", "--json", "-t", str(TEMPLATES / "minimal.tex"), *common])
    assert r.exit_code == 0
    data = json.loads(r.stdout)
    assert data["items"][0]["bullets"][0]["score"] >= data["items"][0]["bullets"][-1]["score"]
    assert data["dropped"]
