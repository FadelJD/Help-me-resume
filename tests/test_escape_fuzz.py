"""Fuzz `cvforge/escape.py` through the real pipeline: build -> compile -> pdftotext.

Each Hypothesis example is a batch of BATCH strings rendered as the bullets of ONE document, so
TOTAL strings cost EXAMPLES compiles instead of TOTAL. Every bullet's text is the fuzzed string
plus a unique marker word (` ZQX0042XQZ`); the marker locates the string's extracted text in the
pdftotext output and keeps each escaped bullet text unique, which `check_traceability` needs
(see `test_duplicate_bullet_text_is_traceable`). The template puts `\\VAR{b.text}` straight after
`\\item`, as templates/minimal.tex does, so a string's first character meets LaTeX exactly as it
would in a real CV.

Property per string: the build succeeds, the PDF compiles with no error, every bullet id is
found in the output, and the sequence of alphanumeric characters (after NFKC, which folds
ligatures such as U+FB01) is the same in the source and in the extracted text. Hyphenation,
line breaks and other non-alphanumeric characters therefore do not count as loss.
"""

from __future__ import annotations

import contextlib
import re
import string
import subprocess
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path

import pytest
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st

from cvforge.errors import CVForgeError
from cvforge.parse import dump_profile
from cvforge.pipeline import build
from cvforge.schema import Bullet, Experience, Person, Profile

pytestmark = pytest.mark.poppler  # compares against pdftotext output

TOTAL = 5000  # strings exercised per run; the work order requires 5,000 to pass
BATCH = 50  # strings per compiled document; at 100 Hypothesis overruns its data budget
EXAMPLES = TOTAL // BATCH
assert EXAMPLES * BATCH >= TOTAL

# Mirrors templates/minimal.tex (preamble and bullet line) without its bullet limit.
TEMPLATE = r"""%% cvforge-template v1
%% sections: experience
%
% Fuzz template for tests/test_escape_fuzz.py: one role, every bullet, nothing else.
\documentclass[11pt]{article}
\usepackage[a4paper,margin=1.8cm]{geometry}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage{enumitem}
\input{glyphtounicode}
\pdfgentounicode=1
\setlength{\parindent}{0pt}
\setlist[itemize]{leftmargin=1.2em, itemsep=1pt, topsep=2pt}
\pagestyle{empty}

\begin{document}
\BLOCK{for job in experience}
\begin{itemize}
\BLOCK{for b in job.bullets}
  \item \VAR{b.text} % id:\VAR{b.id}
\BLOCK{endfor}
\end{itemize}
\BLOCK{endfor}
\end{document}
"""

MARK = "ZQX{:04d}XQZ"
MARK_RE = re.compile(r"ZQX(\d{4})XQZ")

# ---------------------------------------------------------------- alphabet

# Printable ASCII; includes every LaTeX special: & % $ # _ ~ ^ \ { } (and [ ] < > | " ' `).
ASCII = "".join(chr(c) for c in range(0x20, 0x7F))

# Letters that pdflatex with T1 + utf8 inputenc + lmodern both compiles and extracts unchanged
# (measured over U+00A0..U+024F with pdftotext 24.02, TeX Live 2023):
# - All Latin-1 letters.
# - Latin Extended-A except the ones below. pdftotext recombines T1's accent-plus-base
#   constructions (a + macron -> U+0101), so letters without a precomposed T1 glyph still pass.
# Left out, because they fail for font/encoding reasons that escape.py cannot fix:
# - Compile error "Unicode character ... not set up for use with LaTeX":
#   U+0126 U+0127 U+0138 U+013F U+0140 U+0149 U+0166 U+0167 U+017F, and all of Greek,
#   Cyrillic, CJK and most of Latin Extended-B.
# - Compile but extract wrongly: U+0110 extracts as U+00D0; comma-below letters (U+0122/3,
#   U+0136/7, U+013B/C, U+0145/6, U+0156/7, U+0218..U+021B) extract as base letter + ", ";
#   U+0129 U+012B U+012D U+0135 extract on a dotless i/j; ogonek on U+012E/F U+0172/3 is
#   extracted as a detached U+02DB.
LATIN1_LETTERS = "ªµº" + "".join(chr(c) for c in range(0xC0, 0x100) if c not in (0xD7, 0xF7))
LATIN_EXT_A_LETTERS = (
    "ĀāĂăĄąĆćĈĉĊċČčĎďđĒēĔĕĖėĘęĚěĜĝĞğĠġĤĥĨĪĬİıĲĳĴĹĺĽľŁłŃńŇňŊŋŌōŎŏŐőŒœŔŕŘřŚśŜŝŞşŠš"
    "ŢţŤťŨũŪūŬŭŮůŰűŴŵŶŷŸŹźŻżŽž"
)
LETTERS = LATIN1_LETTERS + LATIN_EXT_A_LETTERS

TOKENS = ("C#", "C++", "R&D", "100%", "~/bin", "\n", "\\n", "% id:")

_url_part = st.from_regex(r"[a-z0-9]{1,8}(_[a-z0-9]{1,8}){1,2}", fullmatch=True)
urls = st.builds(
    lambda scheme, host, parts, tail: f"{scheme}{host}.com/{'/'.join(parts)}{tail}",
    st.sampled_from(["", "https://", "http://", "www."]),
    st.from_regex(r"[a-z][a-z_-]{0,9}", fullmatch=True),
    st.lists(_url_part, min_size=1, max_size=3),
    st.sampled_from(["", "/", "?a_b=1&c=2", "#frag_1", "?q=50%25"]),
)
_ascii_char = st.sampled_from(ASCII)
atoms = st.one_of(
    _ascii_char,
    _ascii_char,
    _ascii_char,
    st.sampled_from(LETTERS),
    st.sampled_from(TOKENS),
    urls,
)
_alnum = st.sampled_from(string.ascii_letters + string.digits + LETTERS)
fuzz_strings = st.builds(
    lambda head, anchor, tail: "".join(head) + anchor + "".join(tail),
    st.lists(atoms, max_size=6),
    _alnum,
    st.lists(atoms, max_size=6),
)
batches = st.lists(fuzz_strings, min_size=BATCH, max_size=BATCH)

# ---------------------------------------------------------------- pipeline harness


def alnum(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text) if c.isalnum())


@dataclass
class Outcome:
    error: str | None = None  # build or compile failure
    problems: list[str] = field(default_factory=list)  # per-string losses and trace gaps

    @property
    def ok(self) -> bool:
        return self.error is None and not self.problems

    def describe(self) -> str:
        return self.error or "\n".join(self.problems)


def _profile(strings: list[str]) -> Profile:
    bullets = [Bullet(id=f"b{i:04d}", text=f"{s} {MARK.format(i)}") for i, s in enumerate(strings)]
    role = Experience(
        id="exp-01",
        title="Fuzzer",
        org="Example Org",
        start="2020-01",
        end="present",
        bullets=bullets,
    )
    return Profile(person=Person(name="Fuzz Case"), experience=[role])


def _segments(text: str) -> dict[int, str]:
    """Extracted text of each bullet: from the previous marker to its own marker."""
    out: dict[int, str] = {}
    pos = 0
    for m in MARK_RE.finditer(text):
        out[int(m.group(1))] = " ".join(text[pos : m.start()].split())
        pos = m.end()
    return out


def run_pipeline(strings: list[str], workdir: Path) -> Outcome:
    """Build and compile `strings` as bullets of one CV, then check what pdftotext returns."""
    workdir.mkdir(parents=True)
    profile = workdir / "profile.cv.txt"
    profile.write_text(dump_profile(_profile(strings)), encoding="utf-8")
    template = workdir / "fuzz-template.tex"
    template.write_text(TEMPLATE, encoding="utf-8")
    try:
        with contextlib.chdir(workdir):  # no stray cvforge.toml can change the build
            result = build(
                profile=profile,
                template=template,
                hat=None,
                job=None,
                output=workdir / "cv.tex",
                max_bullets=None,
                compile_pdf_too=True,
            )
    except CVForgeError as exc:
        return Outcome(error=str(exc))
    except Exception as exc:  # a crash is a finding too; keep it bisectable
        return Outcome(error=f"crash: {type(exc).__name__}: {exc}")
    assert result.pdf is not None
    out = Outcome()
    want = {f"exp-01.b{i:04d}" for i in range(len(strings))}
    missing = sorted(want - set(result.report["emitted"]["bullets"]))
    for qid in missing:
        raw = strings[int(qid.rsplit(".b", 1)[1])]
        out.problems.append(f"{raw!r}: bullet {qid} not traced in the .tex (no `% id:` match)")
    out.problems.extend(f"warning: {w}" for w in result.warnings if w.item not in missing)
    text = subprocess.run(
        ["pdftotext", "-enc", "UTF-8", str(result.pdf), "-"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    found = _segments(text)
    for i, raw in enumerate(strings):
        got = found.get(i)
        if got is None:
            out.problems.append(f"{raw!r}: marker {MARK.format(i)} missing from pdftotext output")
        elif alnum(got) != alnum(raw):
            out.problems.append(f"{raw!r}: pdftotext returned {got!r}")
    return out


def isolate(strings: list[str], fails: Callable[[list[str]], bool]) -> list[str]:
    """Smallest failing strings by bisection; the whole group if only a combination fails."""
    if len(strings) <= 1:
        return strings
    half = len(strings) // 2
    bad = [part for part in (strings[:half], strings[half:]) if fails(part)]
    if not bad:
        return strings
    return [s for part in bad for s in isolate(part, fails)]


# ---------------------------------------------------------------- the fuzz


@pytest.mark.tex
def test_fuzz_strings_survive_build_compile_and_extraction(tmp_path: Path) -> None:
    exercised = 0
    dirs = count()

    def fresh() -> Path:
        return tmp_path / f"run{next(dirs):05d}"

    @settings(
        max_examples=EXAMPLES,
        derandomize=True,
        database=None,
        deadline=None,
        phases=(Phase.explicit, Phase.generate),  # shrinking recompiles; bisection is cheaper
        suppress_health_check=list(HealthCheck),
    )
    @given(batches)
    def run(batch: list[str]) -> None:
        nonlocal exercised
        outcome = run_pipeline(batch, fresh())
        if outcome.error is not None:
            culprits = isolate(batch, lambda xs: run_pipeline(xs, fresh()).error is not None)
            pytest.fail(f"build failed for {culprits!r}:\n{outcome.error}", pytrace=False)
        if outcome.problems:
            pytest.fail("text lost:\n" + outcome.describe(), pytrace=False)
        exercised += len(batch)

    run()
    assert exercised >= TOTAL, f"only {exercised} strings exercised, need {TOTAL}"


def test_strategy_meets_its_contract() -> None:
    """Cheap, no TeX: generated strings are bullet-worthy and the counts add up."""
    assert EXAMPLES * BATCH >= TOTAL

    @settings(max_examples=300, derandomize=True, database=None, deadline=None)
    @given(fuzz_strings)
    def run(s: str) -> None:
        assert any(c.isalnum() for c in s)
        assert MARK_RE.search(s) is None

    run()


# ---------------------------------------------------------------- known inputs

KNOWN = [
    "C#",
    "C++",
    "R&D",
    "100%",
    "~/bin",
    "line\nbreak",
    "literal \\n here",
    "github.com/jane_doe/my_repo",
    "https://example.com/path_with_underscores?a=1&b=2#frag",
    "50% of R&D spend on C# & F#",
    "a^2 + b^2 {braces} $5k back\\slash <tag> | pipe",
    "office affinity: fi ff ffi ffl ligatures",
    "Zoë Ångström, Łódź, Kraków, Škoda, Ærøskøbing, İstanbul, Œuvre",
]


@pytest.mark.tex
def test_known_inputs_survive(tmp_path: Path) -> None:
    outcome = run_pipeline(KNOWN, tmp_path / "known")
    assert outcome.ok, outcome.describe()


# ---------------------------------------------------------------- regressions found by the fuzz

# Minimal strings the fuzz found failing (295 of 5,000 before the fixes in this work order),
# kept as permanent regression tests. Fixes: escape.py escapes [ and ] (a leading `[` became
# \\item's optional argument), long tokens get stretchable break points (they overflowed the
# margin and were cut from the text), and the traceability check ignores an escaped "\\% id:".
REGRESSIONS = [
    pytest.param("[h", id="leading-bracket"),
    pytest.param("  [x", id="leading-bracket-after-space"),
    pytest.param("% id:", id="percent-id"),
    pytest.param("100% id:x", id="percent-id-inline"),
    pytest.param("https://example.com/" + "/".join(["abc_def"] * 20), id="long-url"),
    pytest.param(
        "www.sjsf.com/swn_oz0309aw_vh/ty_ngsdi800_6c/r5tmnp9g_3ds30_7b?a_b=1&c=2\u00e2~/bin\u00e3DP",
        id="long-token-no-glue",
    ),
]


@pytest.mark.tex
@pytest.mark.parametrize("raw", REGRESSIONS)
def test_fuzz_regression(raw: str, tmp_path: Path) -> None:
    outcome = run_pipeline([raw], tmp_path / "r")
    assert outcome.ok, outcome.describe()


def _build_plain(texts: list[str], workdir: Path) -> str | None:
    """Build (no compile) with the texts exactly as given, no markers; the error or None."""
    workdir.mkdir(parents=True)
    bullets = [Bullet(id=f"b{i}", text=t) for i, t in enumerate(texts)]
    role = Experience(
        id="exp-01",
        title="Fuzzer",
        org="Example Org",
        start="2020-01",
        end="present",
        bullets=bullets,
    )
    profile = workdir / "profile.cv.txt"
    profile.write_text(
        dump_profile(Profile(person=Person(name="Fuzz Case"), experience=[role])),
        encoding="utf-8",
    )
    template = workdir / "fuzz-template.tex"
    template.write_text(TEMPLATE, encoding="utf-8")
    try:
        with contextlib.chdir(workdir):
            build(
                profile=profile,
                template=template,
                hat=None,
                job=None,
                output=workdir / "cv.tex",
                max_bullets=None,
                compile_pdf_too=False,
            )
    except CVForgeError as exc:
        return str(exc)
    return None


# Regression: check_traceability used to flag any line containing a bullet's text, so repeated
# or overlapping bullet text failed the build. It now matches each bullet on its own id line.
@pytest.mark.parametrize(
    "texts",
    [
        pytest.param(["Led the migration.", "Led the migration."], id="duplicate"),
        pytest.param(["Python", "Python and Go"], id="substring"),
        pytest.param(["experience"], id="in-template-line"),
    ],
)
def test_bullet_text_repeated_elsewhere_still_builds(texts: list[str], tmp_path: Path) -> None:
    assert _build_plain(texts, tmp_path / "t") is None


# ---------------------------------------------------------------- font coverage (not escaping)

_COVERAGE = (
    "font/encoding coverage of pdflatex + T1 + utf8 inputenc + lmodern, not escaping: needs "
    "xelatex/lualatex with a Unicode font, or a template that declares these characters."
)


@pytest.mark.tex
@pytest.mark.xfail(strict=True, reason=_COVERAGE)
@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("Ħamrun", id="no-T1-glyph-compile-error"),
        pytest.param("Ηλίας", id="greek-compile-error"),
        pytest.param("Đorđe", id="D-stroke-extracts-as-Eth"),
        pytest.param("Ștefan", id="comma-below-detached"),
        pytest.param("Kęstutis Šimkūnas Ņina Ģirts Īrija", id="ogonek-macron-on-dotless-i"),
    ],
)
def test_font_coverage_gap(raw: str, tmp_path: Path) -> None:
    outcome = run_pipeline([raw], tmp_path / "c")
    assert outcome.ok, outcome.describe()
