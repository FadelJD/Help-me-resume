# Windows support: what is verified and what is not

Windows support was written without a Windows machine. This page separates what has run from what
is only written to be correct. CI runs on GitHub's hosted `windows-latest` runner, which is a
Windows Server image with developer tools preinstalled. It is not a Windows PC.

## How cvforge behaves on Windows

- **Compile.** cvforge runs the TeX engine (pdflatex, xelatex or lualatex) itself: two passes, and a
  third if the `.aux` file changed. It uses latexmk only when latexmk is on PATH. MiKTeX's latexmk
  needs Perl, so the direct route is the normal one on Windows.
- **Readers that gate.** On Windows these are pdfplumber, pypdf-layout and PDFium (pypdfium2). All
  three install with `pipx install "cvforge[check] ..."`. pdftotext (poppler) runs as an advisory
  reader when it is on PATH and never gates on Windows. pdfminer is advisory on every system. A
  reader that is not installed shows as "not installed" with its install command, and the report
  lists which readers gated.
- **Subprocesses.** Every external program runs through `platforms.run_tool`: an argument list (no
  shell), an explicit working folder, and UTF-8 output decoded with `errors="replace"`.
- **Line endings.** Profiles, hats and templates saved with CRLF build exactly like LF files.
- **`cvforge doctor`** prints the winget command for each missing tool, with scoop and choco as
  alternatives.

## Git for Windows ships a pdftotext that is not poppler's

GitHub's windows-latest image has `C:\Program Files\Git\ucrt64\bin\pdftotext.exe`, reporting
`pdftotext version 4.06 [www.xpdfreader.com]`. That is Xpdf, not poppler, with no `pdfinfo` beside
it. If that folder is on your PATH, cvforge runs it as the advisory pdftotext reader. Its output can
differ from poppler's, and it never gates on Windows. `cvforge doctor` shows "found" for it. It is
unverified whether a default Git for Windows install puts that folder on PATH. CI hides this one
file so the job runs without any pdftotext.

## Verified

| What | Where | Result |
| --- | --- | --- |
| Compiling without latexmk (direct engine runs) | Linux, with latexmk removed from PATH | full suite and corpus pass |
| Windows gate set (pdfplumber, pypdf-layout, pdfium) chosen when the OS reports Windows | Linux, OS faked in tests | pass |
| PDFium on the public template corpus | Linux | see docs/parser-table.md |
| CRLF profile, hat and template | Linux | output identical to LF |
| Test suite, doctor and README install on `windows-latest` | GitHub Actions | not yet: the first run stopped before the tests, because the runner image has a pdftotext on PATH |

## Not verified (needs a real Windows machine)

- The winget ids `Python.Python.3.12`, `Git.Git`, `MiKTeX.MiKTeX`, `oschwartz10612.Poppler` and
  `StrawberryPerl.StrawberryPerl`, and the scoop and choco package names in `cvforge/platforms.py`.
- MiKTeX in any form. CI uses TeX Live, so these are untested: MiKTeX's on-the-fly package
  installs during a non-interactive run, its log format (cvforge also unwraps 79-column lines for
  it), and whether its kpathsea honours the recursive `dir//` TEXINPUTS search that templates with
  their own `.cls` or font files rely on.
- `py -m pipx ensurepath` and the new-terminal step on a fresh Windows user account.
- Console output in Windows PowerShell 5.1 with a legacy code page (CI uses PowerShell 7).
- Templates that need system fonts (the corpus is provisioned by a bash script and runs on
  Linux only).
- The reader table from `check` matches Linux on the same PDF. CI on Windows checks that the gating
  readers pass, not that their text is identical to Linux output.

## Checking it on your own Windows PC

Run these in PowerShell, following the README's Windows block first:

```powershell
cvforge doctor
mkdir my-cv
cd my-cv
cvforge init --example
cvforge build --compile -o out/cv.tex
cvforge check out/cv.tex
```

`doctor` should exit 0 and list pdfplumber, pypdf-layout and pdfium as gating readers. `check`
should end with `check passed: parsed: 3/3 ...`.
