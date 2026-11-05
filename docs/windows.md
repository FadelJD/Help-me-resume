# CV Forge on Windows

Windows support was written without a Windows PC. CI runs it on GitHub's hosted `windows-latest`
machine, a Windows Server image with developer tools already installed. This page lists what has
run there, what is still unknown, and how to try it yourself.

## Install

Follow the Windows block in the [README](../README.md#windows). If you prefer TeX Live to MiKTeX,
install it from [tug.org/texlive/windows.html](https://tug.org/texlive/windows.html). MiKTeX
downloads LaTeX packages the first time a CV needs them. If it asks every time, turn on automatic
installs in the MiKTeX Console, under Settings.

## How CV Forge behaves on Windows

- **Building the PDF:** CV Forge runs pdflatex, xelatex or lualatex itself, two passes plus a third
  when cross-references changed. latexmk is optional, which matters because MiKTeX's latexmk
  needs Perl.
- **Readers that must pass:** pdfplumber, pypdf in layout mode and PDFium. All three come with
  `pipx install "cvforge[check] ..."`. pdftotext never has to pass on Windows: it runs as an extra
  reader when poppler is installed (`winget install oschwartz10612.Poppler`). Many screening tools
  use the same library as pdftotext, so for the fullest check run `check` in WSL or on Linux.
- **Paths:** every path CV Forge prints uses `/`, which Windows accepts.
- **Line endings:** profiles, hats and templates saved with Windows line endings build the same CV.
- **`cvforge doctor`:** prints the winget command for anything missing, with scoop and choco as
  alternatives.

Git for Windows ships its own pdftotext (`C:\Program Files\Git\ucrt64\bin\pdftotext.exe`,
version 4.06 from Xpdf). If that folder is on your PATH, CV Forge uses it as the extra pdftotext
reader, and its output can differ from poppler's. CI hides that one file so its Windows job runs
with no pdftotext at all.

## What has run on windows-latest

| Check | Result |
| --- | --- |
| README Windows block, then `init --example`, `build --compile` and `check` | passes in 36 seconds: `check passed: parsed: 3/3 · advisory: 1/2 · evidence: 100%` |
| `cvforge doctor`, ruff and mypy | pass |
| Test suite, `pytest -m "not corpus"` | passes: 332 passed, 25 skipped |

Test suite history on windows-latest, newest first:

| Commit | Result | What changed |
| --- | --- | --- |
| 8169e6c | 332 passed, 25 skipped | tests expect `/`; the PDF import test needs poppler |
| 7b7d7c0 | 34 failed, 297 passed, 24 skipped | each failure listed: tests still expecting `\` |
| 0205640 | 35 failed, 297 passed, 23 skipped | paths printed with `/`, more TeX packages in CI |
| 0b3276f | 14 failed, 311 passed, 23 skipped, 2 errors | first full run |

The first run failed on paths printed with `\`, a test writing a Windows path into a TOML file,
and LaTeX packages missing from the CI install. All 25 skipped tests need pdftotext, except one
that needs a backslash inside a filename, which Windows does not allow. Importing a PDF with
`cvforge import` also needs pdftotext, on every system.

A test that runs a small Python script saw byte `0xb7` (the `·` in the summary line) arrive in
the Windows code page. Piped output from Python on Windows uses that code page unless
`PYTHONUTF8=1` is set, so `cvforge check --json > report.json` may not write UTF-8 there.

## Still unknown

- The winget ids `Python.Python.3.12`, `Git.Git`, `MiKTeX.MiKTeX`, `oschwartz10612.Poppler` and
  `StrawberryPerl.StrawberryPerl`, and the scoop and choco names in `cvforge/platforms.py`.
- MiKTeX in every respect: CI uses TeX Live. Untested are its automatic package installs during
  a build, its log format, and whether it finds a template's own `.cls` and font files through
  the folder search CV Forge sets up.
- `py -m pipx ensurepath` and reopening PowerShell on a fresh Windows account.
- Windows PowerShell 5.1 with an older code page: CI uses PowerShell 7.
- Templates that need extra fonts: the template corpus runs on Linux.
- Whether a default Git for Windows install puts its pdftotext on PATH.

## Try it on your own PC

After the README's Windows block, in PowerShell:

```powershell
cvforge doctor
mkdir my-cv
cd my-cv
cvforge init --example
cvforge build --compile -o out/cv.tex
cvforge check out/cv.tex
```

`doctor` should exit without errors and mark pdfplumber, pypdf-layout and pdfium as required. `check` should end with `check passed: parsed: 3/3`.
