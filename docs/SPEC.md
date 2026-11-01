# CV Forge — Build Spec for Claude Code

Nov 1, 2026 · @Med

## What this tool is

A command-line tool that turns a plain-text profile into a `.tex` CV built on the user's own LaTeX template, then proves the result survives automated screening. "CV Forge" is a placeholder name; rename it before publishing.

**Inputs**

- `profile.cv.txt` — one plain-text file in the format defined in section 4. The single source of truth.
- A LaTeX template (`.tex`) supplied by the user, following the placeholder contract in section 5.
- Optional: a job description (`job.txt`, or a URL) to tailor against.
- Optional: a profile name (a "hat", e.g. `developer`, `technical-writer`) that weights which items lead.

**Output (fixed, always the same shape)**

- `out/<name>.tex` — the deliverable. Compiles with `latexmk -pdf` with no edits.
- `out/<name>.pdf` — only when `--compile` is passed or during `check`.
- `out/<name>.report.json` and a terminal summary — what was selected, what was dropped, and the screening scores.

**Non-goals**

- No web UI, no accounts, no hosted service.
- Does not design templates. It fills the template the user provides.
- Does not invent experience. The LLM step may reword and reorder; it may not add facts.
- Does not apply to jobs or scrape job boards.

## Design principles

Six rules. Claude Code should refuse a design that breaks any of them.

1. **Deterministic first, LLM last.** Parsing, validation, selection, ranking and rendering run with no network and no model. Only `tailor --rewrite` calls an LLM, and the tool must produce a correct `.tex` without it.
2. **One source of truth.** Everything about the person lives in `profile.cv.txt`. Hats, job ads and templates never carry facts about the person.
3. **Every output line is traceable.** Each bullet in the `.tex` carries a hidden comment `% id:exp-03.b2` pointing to the profile item it came from. A line with no id cannot be emitted.
4. **The LLM may reword and reorder, never add.** Rewritten bullets are diffed against the source item; a rewrite that introduces a number, tool, employer or date not present in the source is rejected automatically.
5. **Template is a contract, not a guess.** A template declares the placeholders it supports in a header block. The tool validates the template before rendering and reports exactly which fields it will and will not fill.
6. **Verified, not assumed.** `check` compiles the PDF, runs it through real parsers, and fails on lost or garbled fields. A CV that only looks right in a viewer has not passed.

Why these matter beyond 2026: screening is moving from keyword matching to models that read the whole document, check that claimed skills are evidenced in the experience, and cross-check against public profiles. Rules 2 to 4 keep the output consistent with reality under that scrutiny; rule 6 keeps it machine-readable whatever parser is in front of it.

## Repo layout

One Python package, one CLI entry point, no framework. Each module has one job and a test file of the same name.

```text
cvforge/
├── pyproject.toml           # package metadata, CLI entry point: cvforge = cvforge.cli:app
├── README.md
├── LICENSE                  # MIT
├── cvforge/
│   ├── cli.py               # Typer app; thin, no logic
│   ├── schema.py            # Pydantic models: Profile, Experience, Bullet, Skill, Hat
│   ├── parse.py             # profile.cv.txt -> Profile (the only place the text format is known)
│   ├── validate.py          # schema + cross-checks (dates, skill ids referenced by bullets exist)
│   ├── select.py            # hat weights + job-ad scoring -> ordered subset of the Profile
│   ├── score.py             # BM25 keyword overlap + local embedding similarity
│   ├── rewrite.py           # optional LLM rewording; enforces the no-new-facts diff
│   ├── template.py          # template contract: declare, validate, render with Jinja2 (LaTeX delimiters)
│   ├── escape.py            # LaTeX escaping of user text, one function, heavily tested
│   ├── compile.py           # latexmk wrapper; returns PDF path or structured error
│   ├── check.py             # parser round-trip + scores -> Report
│   ├── parsers/             # one adapter per parser: pdftotext, pdfplumber, resume-parser
│   └── interview.py         # first-run questions that write profile.cv.txt and config
├── templates/
│   └── minimal.tex          # reference template proving the contract; users bring their own
├── examples/
│   ├── profile.cv.txt       # fictional sample profile
│   ├── job.txt
│   └── hats/developer.toml
├── tests/
│   ├── fixtures/            # profiles, templates, PDFs with known parse results
│   └── test_*.py
└── .github/workflows/
    ├── ci.yml               # lint, type-check, tests
    └── cv-check.yml         # reusable action: build + check a CV on push
```

Dependency direction is one way: `cli` → `select`/`rewrite`/`template`/`check` → `schema`. Nothing imports `cli`. `parse.py` is the only module that knows the text format, so changing the format touches one file.

## Input format

The profile is one plain-text file, `profile.cv.txt`, readable without the tool and editable in any editor. It is a strict subset of YAML so the parser is `ruamel.yaml` plus validation, not a hand-written grammar. Three ways to fill it: write it by hand, run `cvforge init` (interview), or `cvforge add ...` commands that append to it.

**The file**

```yaml
# profile.cv.txt  —  one person, every role, every fact once.
person:
  name: Jane Doe
  email: jane@example.com
  location: Chiang Mai, TH
  links: [github.com/janedoe, linkedin.com/in/janedoe]

skills:                      # id: name — the id is what bullets reference
  py: Python
  dotnet: .NET / C#
  docs: Technical documentation
  latex: LaTeX

experience:
  - id: exp-01
    title: Technical Writer
    org: Acme Software
    start: 2025-06
    end: present
    tags: [docs, dotnet]      # skills this role as a whole evidences
    bullets:
      - id: b1
        text: Owned end-to-end documentation for a .NET PDF library used by 2,000 teams.
        skills: [docs, dotnet]
        weight: 3             # 1–5, how strong this bullet is regardless of job
      - id: b2
        text: Built a Python pipeline migrating 400 knowledge-base articles to DocFX.
        skills: [py, docs]
        weight: 4

projects:
  - id: prj-01
    name: Portfolio site
    url: example.dev
    bullets:
      - id: b1
        text: Static site, Astro, deployed on Cloudflare Pages.
        skills: [py]

education:
  - id: edu-01
    degree: B.Eng. Computer Innovation Engineering
    org: KMITL, Bangkok
    end: 2025-05
```

**Rules the validator enforces**

- Every `skills:` entry on a bullet must be a declared skill id. This is what makes the claimed-vs-evidenced check possible.
- Every `id` is unique within its list. Bullet ids are addressed as `exp-01.b2`.
- Dates are `YYYY-MM` or `present`. No free text.
- `weight` defaults to 3. It is the only subjective field.
- Unknown keys are an error, not a warning. A typo must not silently drop data.

**Hats** (`hats/<name>.toml`) weight skills and section order for a role family. They hold no facts.

```toml
name = "developer"
title_line = "Software Developer"
sections = ["experience", "projects", "skills", "education"]
[skill_weights]
py = 2.0
dotnet = 1.5
docs = 0.5
```

**CLI additions** append to the file through the parser so formatting stays canonical:

```bash
cvforge add skill rust "Rust"
cvforge add bullet exp-01 "Cut build time 40% by caching DocFX output." --skills py,docs --weight 4
```

**Interview** (`cvforge init`): asks name, contact, then loops "add a role? add a bullet for it? which skills does it show?" until the user stops, then writes the file and prints it. Every question has a default or a skip. Nothing the user declines to answer blocks a build.

## LaTeX template contract

A template is an ordinary `.tex` file with Jinja2 tags using LaTeX-safe delimiters, so it still compiles on its own with the sample values and a LaTeX editor does not choke on it. The user keeps full control of packages, fonts and layout; the tool only fills the marked spots.

**Delimiters** (Jinja2 configured, not the defaults)

| Purpose | Syntax | Example |
| --- | --- | --- |
| Value | `\VAR{...}` | `\VAR{person.name}` |
| Block / loop | `\BLOCK{...}` | `\BLOCK{for job in experience}` ... `\BLOCK{endfor}` |
| Comment | `\#{...}` | `\#{ ignored by the tool }` |

**Header block** — the first lines of the template declare what it supports. The tool refuses to render against a template without it, and reports any placeholder in the file not declared here.

```latex
%% cvforge-template v1
%% sections: experience, projects, skills, education
%% supports: person.links, bullet.skills
%% max-bullets-per-role: 5
```

**Available context** (all strings already LaTeX-escaped; the template must not escape again)

- `person` — name, email, location, links (list), title\_line (from the hat)
- `experience`, `projects` — ordered lists; each item has title/name, org, start, end, bullets (ordered list of text)
- `skills` — ordered list of names, grouped if the hat defines groups
- `education` — ordered list
- `meta` — hat name, job title tailored for, build date, tool version

**Minimal valid section**

```latex
\section*{Experience}
\BLOCK{for job in experience}
\textbf{\VAR{job.title}} \hfill \VAR{job.start}--\VAR{job.end}\\
\textit{\VAR{job.org}}
\begin{itemize}
  \BLOCK{for b in job.bullets}
  \item \VAR{b.text} % id:\VAR{b.id}
  \BLOCK{endfor}
\end{itemize}
\BLOCK{endfor}
```

**Escaping** lives in one function, `escape.py`, applied once at render time to every user string: `& % $ # _ { } ~ ^ \`. Tested against a fixture of nasty inputs (C#, 100%, R&D, `~/bin`, URLs with underscores).

**Parser-safety lint** on the template (warnings, shown by `check --lint-template`): two-column layouts, `fontawesome` or other icon fonts, `\includegraphics` for a photo, text in headers/footers, and `fontspec` ligatures without `\usepackage[Ligatures=NoCommon]`. Each is a known cause of garbled extraction. The user can keep them; they are told the cost.

**Bringing your own template** is three steps: add the header block, replace hard-coded values with `\VAR{}` and loops with `\BLOCK{}`, run `cvforge template validate my.tex`. The validator lists every section it will fill and every one it will leave empty.

## Pipeline

Six stages; the first five run offline and the LLM stage is skipped unless asked for. `build` stops after render. `check` continues through compile and verify.

```text
build:  parse -> validate -> select/score -> [rewrite (optional, LLM)] -> render .tex
check:  compile (latexmk) -> extract (parsers) -> round-trip + scores -> report  (failures loop back to profile item / template line)
```

The top row is `build`: profile in, `.tex` out, no network. The bottom row is `check`: it compiles, extracts the text back with real parsers and scores it; a failure points at the profile item or template line that caused it. Rewrite is dashed because it is the only stage that needs a model, and the tool must give a correct `.tex` without it.

## Screening check

`check` answers one question: if a machine reads this PDF, does it get the same facts the profile holds, and does it rank well against the job? It is built around how screening works now and where it is going, not a single vendor.

**How screening works today, in three layers** (each has a different failure mode)

| Layer | What it does | What breaks it | What `check` tests |
| --- | --- | --- | --- |
| Parse | Converts the PDF to fields: name, titles, dates, skills | Ligatures, icon fonts, columns, headers, photos | Round-trip: every profile fact must survive extraction |
| Match | Keyword overlap and semantic similarity to the job ad | Missing vocabulary, generic phrasing | BM25 score + embedding similarity, both reported |
| Read | A model reads the whole CV, checks claims are evidenced, summarises it | Skills listed but never shown in experience; contradictions | Evidence coverage: every emitted skill has at least one bullet |

**Round-trip test** (the core, no model needed)

1. Compile the `.tex` to PDF.
2. Extract text with each parser adapter: `pdftotext`, `pdfplumber`, and one resume-specific parser (the one from Resume Matcher is a candidate; the adapter interface makes it swappable).
3. For every selected item, assert the extracted text contains: the org name, the title, the start and end dates, and each bullet's first eight words.
4. Assert the skills section contains every emitted skill name verbatim.
5. Any miss fails `check` and names the parser, the item id and the string that did not come back.

**Scores** (reported, not gated by default; the user picks thresholds in `cvforge.toml`)

- `keyword`: BM25 overlap between the job ad and the extracted text, plus the list of job-ad terms absent from the CV.
- `semantic`: cosine similarity between job-ad and CV embeddings using a local model (`sentence-transformers/all-MiniLM-L6-v2`; \~90 MB, runs on CPU). No API call.
- `evidence`: share of emitted skills that are backed by at least one selected bullet. Should be 100%.
- `density`: words per page and bullets per role, flagged when outside the template's declared limits.

**Future-proofing** — the parts that stay true as vendors change

- Plain, linear text order is the invariant every layer depends on. The template lint exists for this.
- Models increasingly judge whether claims are evidenced and consistent. The traceability rule and the evidence score are built for that, not for keyword era tricks.
- Keyword stuffing and hidden text are now detectable and penalised. The tool never emits text the reader cannot see.
- Parser adapters are plugins. When a new open-source parser appears, adding it is one file in `parsers/`.

**Explicitly out of scope:** claiming a score against any named commercial ATS. Nobody outside the vendor can reproduce that, and tools that promise it are guessing.

## CLI surface

Eight commands. Every one works with no network. Every one prints a one-line result and exits non-zero on failure so it composes in scripts and CI.

```bash
# first run: interview writes profile.cv.txt and cvforge.toml
cvforge init

# grow the profile without opening the file
cvforge add skill rust "Rust"
cvforge add role "Backend Developer" --org "Acme" --start 2024-01 --end present
cvforge add bullet exp-02 "Shipped a REST API serving 1M requests a day." --skills py --weight 4

# check the profile and a template before building anything
cvforge validate                       # profile only
cvforge template validate my.tex       # template contract + parser-safety lint

# build a .tex (the main command)
cvforge build --template my.tex --hat developer -o out/jane-dev.tex
cvforge build --template my.tex --hat developer --job job.txt -o out/jane-acme.tex
cvforge build ... --compile            # also writes the PDF

# tailor: same as build --job, plus optional LLM rewording with an approval diff
cvforge tailor --template my.tex --hat developer --job job.txt --rewrite
#   shows a before/after diff per bullet; accept all, pick, or reject; then writes the .tex

# prove it: compile, parse round-trip, scores
cvforge check out/jane-acme.tex --job job.txt
cvforge check out/jane-acme.tex --job job.txt --strict   # fail on any score below cvforge.toml thresholds

# see what a build chose and why, without writing anything
cvforge explain --hat developer --job job.txt
```

**Flags shared by `build`, `tailor`, `check`**

- `--hat <name>` — a file in `hats/`; omitted means every item at weight 1.
- `--job <path|url>` — a job ad; a URL is fetched and reduced to text.
- `--max-bullets N` — overrides the template's declared limit downward only.
- `--locale au|uk|us|th` — date format, spelling of "CV/Résumé", page size. Defaults from `cvforge.toml`.
- `--json` — machine-readable output on stdout for agents and scripts.

**`cvforge.toml`** (written by `init`) holds defaults: template path, default hat, locale, score thresholds, LLM provider and model for `--rewrite` (via LiteLLM, so any provider or a local Ollama model works).

## Tech stack

Python 3.11+, installed with `pip install cvforge` or `uv tool install cvforge`. Heavy optional pieces are extras so the base install stays small.

| Concern | Choice | Why | Install group |
| --- | --- | --- | --- |
| CLI | Typer | Typed commands, auto help, `--json` is trivial | base |
| Schema | Pydantic v2 | Validation errors name the field and line | base |
| Profile parsing | ruamel.yaml | Round-trips comments so `add` commands keep the user's formatting | base |
| Templating | Jinja2 with custom delimiters | Standard, well documented, LaTeX-safe when configured | base |
| LaTeX compile | `latexmk` via subprocess | User's own TeX Live; the tool never bundles TeX | base (TeX is a system dependency) |
| Text extraction | pdftotext (poppler), pdfplumber | Two independent extractors catch different failures | check |
| Keyword score | rank-bm25 | Tiny, deterministic | check |
| Semantic score | sentence-transformers, `all-MiniLM-L6-v2` | Local CPU, no API, \~90 MB one-time download | check |
| LLM rewrite | LiteLLM | One interface for Anthropic, OpenAI, Ollama and others; user brings the key | llm |
| Diff display | rich | Side-by-side before/after in the terminal | base |
| Tests | pytest, hypothesis for the escaper | Property tests catch escaping bugs | dev |
| Lint/type | ruff, mypy strict | Keeps agent-written code honest | dev |

**System requirements** the tool checks on first run and reports plainly: `latexmk` on PATH (needed for `--compile` and `check`), `pdftotext` on PATH (needed for `check`). Missing either does not stop `build`.

**Typst** is deliberately not in v1. The template contract and renderer are the only parts that know LaTeX, so a Typst renderer later is a second `template_typst.py`, not a rewrite.

## Claude Code setup

This section is written to be pasted into Claude Code as the opening brief. It tells the agent what exists, what to ask, what to decide, and the order to build in.

**Environment** (cloud session or local, same steps)

```bash
git init cvforge && cd cvforge
uv init --package --python 3.11      # or: python -m venv .venv && pip install -e ".[dev]"
sudo apt-get install -y texlive-latex-base texlive-latex-extra texlive-fonts-recommended latexmk poppler-utils
```

Commit this spec as `docs/SPEC.md` and a short `CLAUDE.md` pointing at it, with the six design principles copied in. Claude Code reads `CLAUDE.md` on every session; the principles belong there, not only in a long spec.

**What the user will provide** (so nothing reads as missing or broken)

- A custom LaTeX template. It will not yet have the header block or `\VAR{}` tags. Converting it to the contract is the agent's job, with the user confirming which parts are fixed and which are filled.
- The user's own profile, entered through `cvforge init` or by editing `profile.cv.txt` directly. The agent never invents sample data in the user's real profile file; sample data goes only in `examples/`.
- Optionally an LLM API key in `cvforge.toml` or an env var. Absent key means `--rewrite` is unavailable and says so; everything else works.

**First-run questions the agent should ask, once, then stop asking**

1. Which hats (role families) to create first, and their names.
2. Which sections the template has, and whether any are fixed text (a tagline, a statement) rather than filled from the profile.
3. Default locale and page size.
4. Whether to gate `check` on score thresholds now or only report. Default: report.
5. Whether an LLM provider is available for `--rewrite`. Default: not configured.

Anything else (module names, library choices, test layout, error-message wording) is decided by the agent from this spec, not asked. If the spec is silent, the agent picks the simplest option and notes it in a `DECISIONS.md` line.

**Build order** — each step ends with passing tests and a commit; do not start the next step until the current one runs end-to-end.

1. `schema.py` + `parse.py` + `validate.py` with the sample profile. `cvforge validate` works.
2. `escape.py` with property tests. Then `template.py` and `templates/minimal.tex`. `cvforge build` produces a compiling `.tex` from the sample.
3. Convert the user's real template to the contract. `cvforge template validate` passes on it. `cvforge build --template user.tex` compiles.
4. `interview.py` and the `add` commands. Round-trip: `init` then `build` on a fresh profile.
5. `select.py` + `score.py` with hats and `--job`. `cvforge explain` shows the ranking and the dropped items.
6. `compile.py`, `parsers/`, `check.py`. The round-trip test fails on a deliberately broken fixture (an icon-font template) and passes on `minimal.tex`.
7. `rewrite.py` with the no-new-facts diff and the approval flow. Only now add LiteLLM.
8. `cv-check.yml` reusable GitHub Action, README with a 60-second quickstart, and the examples folder.

**Working rules for the agent**

- Run `ruff`, `mypy --strict` and `pytest` before every commit; fix, do not suppress.
- A tool error must name the file, the line or item id, and the fix. "Invalid profile" is not an acceptable message.
- Never compile the user's real profile into `examples/` or test fixtures.
- When unsure whether something counts as "adding a fact" in rewrite, treat it as adding. Reject.

## Testing and CI

Two workflows: one tests the tool, one tests a CV. The second is the reusable piece other people will adopt.

**`ci.yml`** (the tool) runs on every push: ruff, mypy strict, pytest with the TeX packages installed so `compile` and `check` tests are real, not mocked. Matrix: Python 3.11 and 3.12, Ubuntu only in v1.

**`cv-check.yml`** (a CV repo) is a reusable action anyone can call from their own CV repository:

```yaml
# .github/workflows/cv.yml in a user's CV repo
on: [push]
jobs:
  cv:
    uses: <org>/cvforge/.github/workflows/cv-check.yml@v1
    with:
      template: cv.tex
      hat: developer
      strict: false
```

It builds, compiles, runs `check`, uploads the PDF and `report.json` as artifacts, and writes a badge-ready summary (`parsed: 3/3 · keyword: 0.71 · evidence: 100%`). This is the README's headline demo.

**Fixtures** in `tests/fixtures/`

- `profile_ok.cv.txt`, `profile_bad_*.cv.txt` — one bad file per validation rule.
- `template_minimal.tex`, `template_icons.tex` (icon font, must fail round-trip), `template_twocol.tex` (must warn).
- `escape_cases.txt` — every special character case, including `C#`, `R&D`, `100%`, `~/path`, `file_name`.
- `job_backend.txt`, `job_writer.txt` — two job ads that should rank different bullets first under the same hat.

**Acceptance criteria for v1.0** — all must hold on the sample profile and on the user's real template

- [ ] `build` runs with no network and produces a `.tex` that `latexmk -pdf` compiles with zero edits.
- [ ] Every bullet in the `.tex` carries a traceable `% id:` comment.
- [ ] `check` round-trip passes on `minimal.tex` and fails, naming the lost string, on `template_icons.tex`.
- [ ] Two different job ads reorder bullets differently under the same hat; `explain` shows why.
- [ ] `--rewrite` rejects a rewrite that adds a number or tool not in the source bullet (tested with a canned LLM response).
- [ ] `init` on an empty directory produces a profile that `validate` accepts.
- [ ] A user converting their own template reaches a compiling build in under 30 minutes following the README alone.

## Roadmap

v1.0 is the build order in the Claude Code section, finished. Everything below is after that, in priority order, and none of it changes the core.

1. **Typst renderer** — second template engine behind the same contract; faster compile, no TeX install for users who want it.
2. **DOCX and plain-text export** — from the same selected profile, for portals that reject PDF.
3. **MCP server** — exposes `build`, `tailor`, `check` as tools so Claude Code, Cursor or any agent can drive the loop. Thin wrapper over the CLI with `--json`.
4. **Cover letter** — same hat and job ad, a second template, same traceability rule.
5. **Public profile consistency check** — optional comparison of the `.tex` against a LinkedIn or GitHub export the user supplies, flagging date or title mismatches before a screener does.
6. **Template gallery** — community-contributed templates that pass the lint, each with a parse-safety score shown in the README.

**Not planned**: a web app, hosted accounts, job scraping, auto-apply. Those are different products and would pull the repo away from being a tool people trust with their own data.

**Naming**: pick a name that is not "resume-builder" or "cv-generator"; both are taken many times over. Tag the repo `ats`, `latex`, `cv`, `json-resume`, `cli`, `mcp`.
