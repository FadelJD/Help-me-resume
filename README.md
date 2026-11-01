# Help-me-resume (working name: CV Forge)

A command-line tool that turns one plain-text profile into a `.tex` CV built on **your own LaTeX
template**, then proves the PDF survives automated screening by reading it back with real parsers.

- **Deterministic.** Parsing, selection, ranking and rendering run offline with no model.
- **Traceable.** Every bullet in the `.tex` carries `% id:exp-01.b2`, pointing at the profile line it came from.
- **Verified.** `cvforge check` compiles the PDF, extracts it with three independent parsers, and fails
  if any title, employer, date, bullet or skill does not come back intact.
- **Honest.** The optional LLM step may reword; a rewrite that adds a number, tool, employer or date is
  rejected automatically.

## 60-second quickstart

You need Python 3.11+ and TeX Live with `latexmk`, plus poppler for `check`.

```bash
sudo apt-get install -y latexmk texlive-latex-extra texlive-fonts-recommended lmodern poppler-utils
```

```bash
pip install "cvforge[check] @ git+https://github.com/FadelJD/Help-me-resume@main"
```

Build and check the fictional example from a clone of this repository:

```bash
cvforge build -p examples/profile.cv.txt -t templates/minimal.tex --hat examples/hats/developer.toml --job examples/job.txt -o out/jane.tex
```

```bash
cvforge check out/jane.tex --job examples/job.txt
```

The last line reads like `check passed: parsed: 3/3 · keyword: 0.49 · evidence: 100%`.

Then start your own profile in an empty folder:

```bash
cvforge init
```

## Commands

Every command works offline, prints a one-line result, exits non-zero on failure, and takes `--json`.

| Command | What it does |
| --- | --- |
| `cvforge init` | Interview that writes `profile.cv.txt`, `cvforge.toml` and starter hats. |
| `cvforge add skill\|role\|bullet\|project\|education ...` | Append to the profile without opening it; comments are kept. |
| `cvforge validate` | Check the profile: unknown keys, dates, ids, skill references. |
| `cvforge template validate my.tex` | Check a template's contract and lint it for parser-unsafe layout. |
| `cvforge build --template my.tex --hat developer [--job job.txt] [--compile]` | Render the `.tex` and `report.json`. |
| `cvforge explain --hat developer --job job.txt` | Show the ranking and what was dropped, without writing. |
| `cvforge tailor --job job.txt [--rewrite]` | Build against a job ad; optionally offer LLM rewording you approve. |
| `cvforge check out/cv.tex [--job job.txt] [--strict]` | Compile, parse back, score. |

Shared flags: `--hat`, `--job` (file or URL), `--max-bullets` (can only lower the template's limit),
`--locale au|uk|us|th`. Defaults live in `cvforge.toml`.

## The profile

One YAML-subset file holds every fact once. Bullets reference skill ids, which is what lets `check`
prove each listed skill is backed by experience. See [`examples/profile.cv.txt`](examples/profile.cv.txt).

```yaml
skills:
  py: Python
experience:
  - id: exp-01
    title: Technical Writer
    org: Acme Software
    start: 2025-06
    end: present
    bullets:
      - id: b2
        text: Built a Python pipeline migrating 400 knowledge-base articles to DocFX.
        skills: [py]
        weight: 4
```

**Hats** (`hats/<name>.toml`) weight skills and set section order for a role family. They hold no
facts. This repo ships `developer`, `full-stack-engineer` and `technical-writer` examples.

## Bring your own template

1. Add the header block as the first lines:

   ```latex
   %% cvforge-template v1
   %% sections: experience, projects, skills, education
   %% supports: person.links, person.phone
   %% max-bullets-per-role: 5
   ```

2. Replace hard-coded text with `\VAR{person.name}` and loops with `\BLOCK{for job in experience}` ...
   `\BLOCK{endfor}`. End every bullet line with `% id:\VAR{b.id}`.
3. Run `cvforge template validate my.tex` until it reports `valid`, then `cvforge build`.

All values arrive LaTeX-escaped; do not escape again. [`templates/minimal.tex`](templates/minimal.tex)
is a complete working example, and [`docs/SPEC.md`](docs/SPEC.md) lists every available field.

**Parser-safety lint.** Two-column layouts, icon fonts, photos, text in headers or footers, and
`fontspec` ligatures each garble extraction. The validator warns about each; you decide.

## What `check` tests

| Layer | Test |
| --- | --- |
| Parse | pdftotext, pdfplumber and pypdf must each return every emitted name, title, employer, date, the first eight words of every bullet, and every skill, as whole words. |
| Match | Keyword coverage of the job ad, plus the heaviest job terms missing from the CV. Optional local embedding similarity with `cvforge[semantic]`. |
| Read | Evidence: the share of listed skills backed by a shown bullet. Should be 100%. |

Scores are reported, not enforced, unless you pass `--strict` (thresholds in `cvforge.toml`).
`check` never claims a score against a named commercial ATS; nobody outside the vendor can reproduce one.

## Use it in CI

Call the reusable workflow from your CV repository:

```yaml
on: [push]
jobs:
  cv:
    uses: FadelJD/Help-me-resume/.github/workflows/cv-check.yml@main
    with:
      template: cv.tex
      hat: developer
      strict: false
```

It builds, compiles, runs `check`, uploads the PDF and `report.json`, and writes a summary line such
as `parsed: 3/3 · keyword: 0.71 · evidence: 100%`.

## Optional LLM rewording

```bash
pip install "cvforge[llm]"
```

Set `[llm] model = "ollama/llama3"` (or any LiteLLM model string) in `cvforge.toml`, then run
`cvforge tailor --job job.txt --rewrite`. You see a before-and-after table and accept all, pick, or
reject. Without a model configured, `--rewrite` says so and everything else works.

## Known limits

- pypdf runs in layout mode. Its default mode splits most kerning pairs in TeX output ("T echnical"),
  in every font tried, so tools built on that mode will see those spaces whatever the template.
- The semantic score is optional and was not exercised in development, because the build environment
  could not download the embedding model.

## Development

```bash
pip install -e ".[dev,check]"
```

```bash
ruff check . && ruff format --check . && mypy cvforge && pytest -q
```

Design rules live in [`CLAUDE.md`](CLAUDE.md), the full spec in [`docs/SPEC.md`](docs/SPEC.md), and
every choice the spec left open in [`DECISIONS.md`](DECISIONS.md).

MIT licensed.
