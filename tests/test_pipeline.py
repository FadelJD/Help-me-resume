from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path

import pytest

from cvforge import pipeline
from cvforge.errors import CVForgeError
from cvforge.template import ids_in_tex

from .conftest import EXAMPLES, FIXTURES, TEMPLATES


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def guard(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access during an offline command")

    monkeypatch.setattr(socket.socket, "connect", guard)


def _build(out: Path, **kw: object) -> pipeline.BuildResult:
    args: dict[str, object] = {
        "profile": EXAMPLES / "profile.cv.txt",
        "template": TEMPLATES / "minimal.tex",
        "hat": str(EXAMPLES / "hats" / "developer.toml"),
        "job": None,
        "output": out,
        "max_bullets": None,
        "compile_pdf_too": False,
    }
    args.update(kw)
    return pipeline.build(**args)  # type: ignore[arg-type]


def test_build_writes_tex_and_report(workdir: Path, no_network: None) -> None:
    result = _build(workdir / "out" / "jane.tex", job=str(FIXTURES / "job_backend.txt"))
    tex = result.tex.read_text()
    report = json.loads(result.report_path.read_text())
    ids = ids_in_tex(tex)
    assert sorted(ids) == report["emitted"]["bullets"]
    assert len(ids) == 12  # template limit 5: exp-01 drops one of six
    assert any(d["kind"] == "bullet" for d in report["dropped"])
    assert report["emitted"]["skills"]


def test_every_bullet_line_has_an_id(workdir: Path) -> None:
    tex = _build(workdir / "o.tex").tex.read_text()
    for line in tex.splitlines():
        if line.strip().startswith("\\item"):
            assert "% id:" in line, line


def test_max_bullets_only_lowers(workdir: Path) -> None:
    low = _build(workdir / "a.tex", max_bullets=2)
    assert len(low.report["emitted"]["bullets"]) == 6  # 2 + 2 roles, 1 + 1 projects
    high = _build(workdir / "b.tex", max_bullets=9)
    assert any("can only lower" in w.fix for w in high.warnings)
    assert len(high.report["emitted"]["bullets"]) == 12


def test_locale_changes_paper(workdir: Path) -> None:
    pipeline.override_locale("us")
    try:
        tex = _build(workdir / "us.tex").tex.read_text()
    finally:
        pipeline._LOCALE_OVERRIDE.clear()
    assert "letterpaper" in tex


def test_bad_locale() -> None:
    with pytest.raises(CVForgeError):
        pipeline.override_locale("fr")


def test_invalid_template_stops_build(workdir: Path) -> None:
    with pytest.raises(CVForgeError) as exc:
        _build(workdir / "x.tex", template=FIXTURES / "template_noid.tex")
    assert "id:" in str(exc.value)


def test_config_supplies_defaults(workdir: Path) -> None:
    (workdir / "hats").mkdir()
    (workdir / "hats" / "developer.toml").write_text(
        (EXAMPLES / "hats" / "developer.toml").read_text()
    )
    (workdir / "profile.cv.txt").write_text((EXAMPLES / "profile.cv.txt").read_text())
    (workdir / "cvforge.toml").write_text(
        f'template = "{TEMPLATES / "minimal.tex"}"\nhat = "developer"\n'
    )
    result = pipeline.build(
        profile=None,
        template=None,
        hat=None,
        job=None,
        output=None,
        max_bullets=None,
        compile_pdf_too=False,
    )
    assert result.tex == Path("out/jane-doe-developer.tex")
    assert "Software Developer" in result.tex.read_text()


def test_html_to_text() -> None:
    html = "<html><style>x{}</style><h1>Backend Dev</h1><p>Node.js &amp; SQL</p></html>"
    assert pipeline.html_to_text(html) == "Backend Dev\nNode.js & SQL"


@pytest.mark.tex
@pytest.mark.poppler
def test_build_compiles_with_zero_edits(workdir: Path, no_network: None) -> None:
    result = _build(workdir / "out" / "jane.tex", compile_pdf_too=True)
    assert result.pdf is not None and result.pdf.exists()
    text = subprocess.run(
        ["pdftotext", str(result.pdf), "-"], capture_output=True, text=True, check=True
    ).stdout
    assert "Jane Doe" in text and "Acme Software" in text
