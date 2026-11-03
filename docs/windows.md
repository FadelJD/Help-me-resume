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
| README Windows block, then `init --example`, `build --compile`, `check` | GitHub Actions `windows-latest` (TeX Live, no poppler, no latexmk) | pass: `check passed: parsed: 3/3 · advisory: 1/2 · evidence: 100%`, 36 s |
| `cvforge doctor`, ruff, mypy on Windows | GitHub Actions `windows-latest` | pass |
| Test suite (`pytest -m "not corpus"`) on Windows | GitHub Actions `windows-latest` | **fail**: 14 failed, 311 passed, 23 skipped, 2 errors; see below |

## Known failures on windows-latest (CI run 41619086781, not fixed yet)

| Tests | Error (verbatim) | Apparent cause |
| --- | --- | --- |
| test_cli::test_build_and_explain | `assert 'out\\x.tex' == 'out/x.tex'` | JSON output uses Windows path separators; the test expects `/` |
| test_hats::test_saved_explain_json_matches_pipeline (8 cases) | `{'job': 'examples\\people\\...txt'} != {'job': 'examples/people/...txt'}` | the same, in `explain --json` |
| test_errors::test_errors_doc_is_current | `docs/errors.md is stale` (only `\` vs `/` differ) | the same, in error messages |
| test_pipeline::test_config_supplies_defaults | `invalid TOML: Unescaped '\' in a string (at line 1, column 17)` | the test writes a Windows path into a TOML basic string |
| test_check::test_roundtrip_fails_on_icon_template_naming_the_string, test_check::test_twocol_template_warns_in_lint, test_importer::test_import_reproduces_the_source_profile (2 errors) | `LaTeX error: Emergency stop. (engines tried: pdflatex)` | inferred, not confirmed: the lines load marvosym, paracol, fullpage/titlesec, which the CI's minimal TeX Live install lacks |
| test_cli::test_check_cli_exit_codes | `KeyError: 'badge'` | not known; possibly the same missing-package compile failure |

One warning: a test subprocess printed `·` and the reader got byte `0xb7` (`'utf-8' codec can't
decode byte 0xb7`). Python on Windows writes piped output in the ANSI code page unless
`PYTHONUTF8=1` is set, so piping `cvforge check --json` output to a file may not produce UTF-8 on
Windows. Unverified beyond that one warning.

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
