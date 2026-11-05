"""cvforge prints every path with `/`, on every system. These tests pretend to be Windows."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from cvforge import pipeline
from cvforge.errors import Issue
from cvforge.platforms import show_path

from .conftest import EXAMPLES, TEMPLATES


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cvforge.platforms.current_os", lambda: "windows")


def test_show_path_on_windows(windows: None) -> None:
    assert show_path("out\\cv.tex") == "out/cv.tex"
    assert show_path("C:\\Users\\me\\cv.pdf") == "C:/Users/me/cv.pdf"


def test_show_path_keeps_backslashes_elsewhere(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cvforge.platforms.current_os", lambda: "linux")
    assert show_path("odd\\name.txt") == "odd\\name.txt"  # a legal Linux filename


def test_errors_print_forward_slashes(windows: None) -> None:
    issue = Issue(file="tests\\fixtures\\bad.cv.txt", line=3, message="m.", fix="f.")
    assert str(issue).startswith("tests/fixtures/bad.cv.txt:3: error:")
    assert issue.to_dict()["file"] == "tests/fixtures/bad.cv.txt"


def test_explain_and_build_print_forward_slashes(
    windows: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # On Linux a backslash is a legal filename character, so these names are what a Windows
    # user would type; the output must still show `/`.
    monkeypatch.chdir(tmp_path)
    Path("jobs\\ad.txt").write_text((EXAMPLES / "job.txt").read_text(encoding="utf-8"))
    common = {
        "profile": EXAMPLES / "profile.cv.txt",
        "template": TEMPLATES / "minimal.tex",
        "hat": str(EXAMPLES / "hats" / "developer.toml"),
        "job": "jobs\\ad.txt",
        "max_bullets": None,
    }
    assert pipeline.explain(**common).job == "jobs/ad.txt"  # type: ignore[arg-type]
    result = pipeline.build(  # type: ignore[arg-type]
        **common, output=Path("out\\cv.tex"), compile_pdf_too=False
    )
    assert result.report["job"] == "jobs/ad.txt"
    assert result.report["tex"] == "out/cv.tex"
    assert result.summary.startswith("wrote out/cv.tex ")


def test_init_writes_valid_toml_with_a_windows_template_path(windows: None, tmp_path: Path) -> None:
    text = pipeline.DEFAULT_CONFIG_TEXT.format(
        template=show_path("C:\\cv\\my.tex"), hat="developer", locale="th"
    )
    assert tomllib.loads(text)["template"] == "C:/cv/my.tex"
