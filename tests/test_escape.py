from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cvforge.compile import compile_pdf
from cvforge.escape import _SPECIAL, BREAK, escape, escape_url

from .conftest import FIXTURES

_INVERSE = {v: k for k, v in _SPECIAL.items()}
_INVERSE[BREAK] = ""  # an invisible line-break opportunity
_TOKEN = re.compile("|".join(re.escape(v) for v in sorted(_INVERSE, key=len, reverse=True)))
_BARE = set("\\&%$#_{}~^<>|")


def _unescape(s: str) -> str:
    return _TOKEN.sub(lambda m: _INVERSE[m.group(0)], s)


def _no_bare_specials(s: str) -> bool:
    return not (set(_TOKEN.sub("", s)) & _BARE)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("C#", r"C\#"),
        ("R&D", r"R\&D"),
        ("100%", r"100\%"),
        ("~/bin", r"\textasciitilde{}/bin"),
        ("file_name", r"file\_name"),
        ("back\\slash", r"back\textbackslash{}slash"),
        ("a^2", r"a\textasciicircum{}2"),
        ("line\nbreak", "line break"),
        ("  padded  ", "padded"),
    ],
)
def test_known_cases(raw: str, expected: str) -> None:
    assert escape(raw) == expected


def test_escape_is_not_applied_twice() -> None:
    assert escape(r"\&") == r"\textbackslash{}\&"


# Printable text: escaping must be lossless and leave no bare special characters.
printable = st.text(st.characters(blacklist_categories=("Cc", "Cs", "Zl", "Zp", "Cf")))


@given(printable)
def test_property_round_trip(s: str) -> None:
    out = escape(s)
    assert _no_bare_specials(out)
    assert _unescape(out) == " ".join(s.split())


@given(st.text())
def test_property_never_emits_newline_or_bare_special(s: str) -> None:
    out = escape(s)
    assert "\n" not in out and "\r" not in out
    assert _no_bare_specials(out)


@given(st.text())
def test_property_url_has_no_bare_percent_or_hash(s: str) -> None:
    out = escape_url(s)
    assert re.search(r"(?<!\\)[%#]", out) is None
    assert not any(c.isspace() for c in out)


@pytest.mark.tex
@pytest.mark.poppler
def test_fixture_cases_compile_and_extract(tmp_path: Path) -> None:
    lines = (FIXTURES / "escape_cases.txt").read_text(encoding="utf-8").splitlines()
    body = "\n\n".join(escape(line) for line in lines)
    tex = tmp_path / "e.tex"
    tex.write_text(
        "\\documentclass{article}\n\\usepackage[T1]{fontenc}\n\\usepackage{lmodern}\n"
        f"\\begin{{document}}\n{body}\n\\end{{document}}\n",
        encoding="utf-8",
    )
    compile_pdf(tex)
    assert shutil.which("pdftotext")
    text = subprocess.run(
        ["pdftotext", str(tmp_path / "e.pdf"), "-"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout
    flat = " ".join(text.split())
    for line in lines:
        assert line in flat, line


def test_long_tokens_get_break_opportunities() -> None:
    url = "github.com/jane_doe/a_really_long_repository_name"
    out = escape(url, breakable=True)
    assert BREAK in out
    assert BREAK not in escape(url)  # emails and links may be reused inside URLs
    assert escape("short words stay as they are") == "short words stay as they are"


@pytest.mark.tex
@pytest.mark.poppler
def test_regression_long_url_is_not_cut_at_the_margin(tmp_path: Path) -> None:
    # Found by the escaper fuzz: an unbreakable URL ran past the margin and pdftotext lost it.
    url = "https://example.com/" + "/".join(f"segment_{i:02d}_abcdefgh" for i in range(12))
    tex = tmp_path / "u.tex"
    tex.write_text(
        "\\documentclass{article}\n\\usepackage[T1]{fontenc}\n\\usepackage{lmodern}\n"
        f"\\pagestyle{{empty}}\\begin{{document}}\n{escape(url, breakable=True)}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    compile_pdf(tex)
    text = subprocess.run(
        ["pdftotext", str(tmp_path / "u.pdf"), "-"],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout
    assert "".join(text.split()) == url
