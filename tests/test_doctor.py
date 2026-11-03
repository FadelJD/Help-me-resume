from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

import cvforge.doctor as doctor_module
from cvforge.cli import app
from cvforge.doctor import diagnose, missing_required

from .conftest import EXAMPLES, TEMPLATES

runner = CliRunner()


def _by_name(items: list[doctor_module.Item]) -> dict[str, doctor_module.Item]:
    return {i.name: i for i in items}


def test_linux_gates_are_required() -> None:
    items = _by_name(diagnose("linux"))
    assert items["reader pdftotext"].required and items["reader pdfplumber"].required
    assert not items["reader pdfium"].required and not items["reader pdfminer"].required
    assert not items["latexmk"].required and not items["semantic score"].required


def test_windows_gates_and_install_commands() -> None:
    # Simulated on Linux: which readers are required, and which commands are shown.
    items = _by_name(diagnose("windows"))
    assert items["reader pdfium"].required and not items["reader pdftotext"].required
    assert "winget" in items["tex engine"].fix and "winget" in items["reader pdftotext"].fix
    assert "scoop" in items["reader pdftotext"].fix and "choco" in items["reader pdftotext"].fix


def test_macos_commands_use_brew() -> None:
    items = _by_name(diagnose("macos"))
    assert items["tex engine"].fix.startswith("brew") and "brew" in items["reader pdftotext"].fix


def test_missing_engine_fails_with_the_install_command(monkeypatch: pytest.MonkeyPatch) -> None:
    real = shutil.which

    def which(name: str, *args: object, **kwargs: object) -> str | None:
        return None if name in ("pdflatex", "xelatex", "lualatex") else real(name)

    monkeypatch.setattr(doctor_module.shutil, "which", which)
    assert "tex engine" in missing_required("linux")
    r = runner.invoke(app, ["doctor"])
    assert r.exit_code == 1
    line = next(ln for ln in r.stdout.splitlines() if "tex engine" in ln)
    assert line.startswith("MISSING") and "install:" in line


def test_missing_optional_tool_keeps_exit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    real = shutil.which
    monkeypatch.setattr(
        doctor_module.shutil, "which", lambda n, *a, **k: None if n == "latexmk" else real(n)
    )
    if missing_required():
        pytest.skip("this machine lacks a required tool; covered by the test above")
    r = runner.invoke(app, ["doctor", "--json"])
    assert r.exit_code == 0 and '"latexmk"' in r.stdout


def test_build_and_init_point_at_doctor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import cvforge.cli as cli_module

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "missing_required", lambda: ["tex engine"])
    r = runner.invoke(
        app, ["build", "-p", str(EXAMPLES / "profile.cv.txt"), "-t", str(TEMPLATES / "minimal.tex")]
    )
    assert r.exit_code == 0 and "run cvforge doctor" in r.stderr
    r = runner.invoke(app, ["init", "--defaults"])
    assert r.exit_code == 0 and "run cvforge doctor" in r.stderr
