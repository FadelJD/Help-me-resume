"""Files saved on Windows (CRLF line ends) build exactly like LF files."""

from __future__ import annotations

from pathlib import Path

import pytest

from cvforge import pipeline
from cvforge.template import ids_in_tex

from .conftest import EXAMPLES, TEMPLATES


def _crlf_copy(src: Path, dst: Path) -> Path:
    text = src.read_text(encoding="utf-8")
    dst.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    assert b"\r\n" in dst.read_bytes()
    return dst


def _build(profile: Path, template: Path, hat: Path, out: Path) -> str:
    result = pipeline.build(
        profile=profile,
        template=template,
        hat=str(hat),
        job=None,
        output=out,
        max_bullets=None,
        compile_pdf_too=False,
    )
    return result.tex.read_text(encoding="utf-8")


def test_build_from_crlf_profile_template_and_hat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1793404800")
    hat = EXAMPLES / "hats" / "developer.toml"
    lf = _build(EXAMPLES / "profile.cv.txt", TEMPLATES / "minimal.tex", hat, tmp_path / "lf.tex")
    crlf = _build(
        _crlf_copy(EXAMPLES / "profile.cv.txt", tmp_path / "p.cv.txt"),
        _crlf_copy(TEMPLATES / "minimal.tex", tmp_path / "t.tex"),
        _crlf_copy(hat, tmp_path / "h.toml"),
        tmp_path / "crlf.tex",
    )
    assert crlf == lf
    assert ids_in_tex(crlf) == ids_in_tex(lf) and ids_in_tex(crlf)


def test_add_to_crlf_profile(tmp_path: Path) -> None:
    profile = _crlf_copy(EXAMPLES / "profile.cv.txt", tmp_path / "p.cv.txt")
    pipeline.add_skill(profile, "rust", "Rust")
    text = profile.read_text(encoding="utf-8")
    assert "rust: Rust" in text and "\r" not in text


def test_crlf_ids_parse_from_raw_text() -> None:
    raw = "\\item Shipped it. % id:exp-01.b1\r\n\\item More. % id:exp-01.b2\r\n"
    assert ids_in_tex(raw) == ["exp-01.b1", "exp-01.b2"]
