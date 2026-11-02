# Decisions

Choices the spec leaves open. One line each, newest last.

- Repo root is the package root (spec's outer `cvforge/` folder = this repo); the Python package lives in `cvforge/`.
- Package and CLI keep the placeholder name `cvforge` until a final name is chosen; renaming is a mechanical find/replace.
- Branching: `main` holds releases, `develop` is the integration branch, feature branches merge into `develop` by PR.
- Build tooling: `uv` with a `hatchling` backend; `pip install -e ".[dev]"` also works.

## Project answers (first-run questions, asked once)

- Hats to start with: `full-stack-engineer`, `developer`, `technical-writer`.
- Default locale `th`: A4 paper, "CV" wording.
- `check` reports scores only; thresholds apply only with `--strict`.
- No LLM provider configured; `tailor --rewrite` reports that it is unavailable.

## Step 1: schema, parse, validate

- Added optional `person.phone` and `experience.location`; both are common CV fields the spec omits.
- Item ids are unique across experience, projects and education, so `exp-01.b2` is never ambiguous.
- Shared `Issue` type lives in `errors.py`; command orchestration lives in `pipeline.py` so `cli.py` stays thin.
- Defaults live in `config.py` (`cvforge.toml` is optional; every key has a default).
- A declared skill no bullet references is a warning, not an error: it is valid but will never be shown.
- `tests/` is a package so tests can import shared paths from `conftest.py`.

## Step 2: escape, template, build

- `escape.py` has two functions: `escape()` for body text and `escape_url()` for `\href` targets, which need different rules.
- The escaper also handles `< > |`, strips control/zero-width characters and collapses newlines, so user text can never hide or split a `% id:` line.
- Templates are compiled after rendering; compiling an unrendered template on its own is not a goal.
- Template comments are parsed by Jinja too, so a comment must not contain literal `\VAR{` or `\BLOCK{`.
- `%% supports:` features: person.links, person.phone, experience.location, bullet.skills, projects.url, skills.groups. Core fields need no declaration.
- Optional header key `%% max-pages: N` feeds the density check.
- Context: `skills` is always a flat list of names; `skill_groups` is a separate list of {name, skills}. Links and project URLs come as {text, href}.
- Dates render as `Jun 2025` / `Present` in every locale; locales differ in paper size and CV/Résumé wording. Raw `YYYY-MM` is available as `start_raw`/`end_raw`.
- `templates/minimal.tex` puts dates inline. Revised in review: this was chosen from raw pdftotext output before `check` existed, not from a check failure. `templates/minimal-right-dates.tex` restores right-aligned dates and passes every gating parser.
- Traceability is enforced twice: statically (bullet text and `% id:` on the same template line) and after render (each output line holding bullet text carries the matching id).
- Selection result types live in `schema.py` as dataclasses, so `template.py` depends only on `schema`.
- `build_date` honours `SOURCE_DATE_EPOCH` for reproducible output.
- `views.py` holds rich terminal rendering so `cli.py` stays thin.
- BM25 is implemented in `score.py` (about 30 lines) instead of `rank-bm25`, which pulls numpy; `build --job` stays dependency-free and offline.
- TeX system packages for dev and CI: texlive-latex-base, texlive-latex-extra, texlive-fonts-recommended, lmodern, latexmk, poppler-utils.

## Step 4: init and add

- `init` asks for the name with default "Your Name" so an all-defaults run still yields a valid profile; nothing else is required.
- In the interview, skills can be named freely; unknown names become new skills with a slug id (".NET / C#" becomes `net-c`).
- An invalid date is re-asked; a start date defaults to the current month and an end date to `present`.
- `init` also writes starter hats (full-stack-engineer, developer, technical-writer) with every declared skill at weight 1.0, ready to tune.
- `init --defaults` runs the interview non-interactively; `init` refuses to overwrite without `--force`.
- `add` commands validate the whole would-be file and write nothing on error.

## Step 5: select, score, explain

- Bullet score = weight x hat factor x (1 + job relevance). Hat factor is the largest hat weight among the bullet's skills (1.0 for unlisted skills and without a hat); job relevance is BM25 scaled to 0..1.
- "No hat means every item at weight 1" is read as hat factor 1.0; the bullet's own weight still counts.
- Roles stay reverse-chronological whatever the scores; only bullets within a role, projects and skills are reordered.
- Emitted skills are exactly those evidenced by a selected bullet, so the evidence score is 100% by construction. A hat weight of 0 hides a skill.
- Tokenizer keeps tech terms (`c#`, `.net`, `node.js`), drops stopwords and job-ad boilerplate, and strips a plural `s` from alphabetic words.
- `explain` applies the template's bullet limit when a template is given or configured; otherwise it shows the full ranking.

## Step 6: compile, parsers, check

- Third parser is `pypdf`, not a resume-specific parser (accepted in review). Revised by research (docs/research.md): Resume Matcher calls `pdfminer.high_level.extract_text`, whose output differs from pdfplumber's `extract_text()` (pdfplumber glues words on some fonts), so a pdfminer high-level adapter would add a distinct reading. Recommended, not built (work order 2 item 7 says no code).
- Revised in review: two pypdf adapters. `pypdf-layout` gates; `pypdf` default mode (LangChain's PyPDFLoader) is advisory and its misses are warnings that show what it read ("T echnical W riter"), because it splits kerning pairs in every font and template tested.
- Round-trip matching is whole-word: a fact glued to an icon glyph or a neighbouring word counts as lost, because a parser reading that text gets the wrong value. `(cid:N)` and private-use glyphs count as junk.
- Extracted text is normalized before matching (NFKC, dashes, curly quotes, line-end hyphens read both ways).
- The round-trip also checks the name, email and phone when the template shows them. Which fields the template shows is recorded in report.json at build time.
- `check` requires the report.json that `build` writes beside the .tex; it holds the emitted text (including approved rewrites) and evidence.
- The icon fixture uses Marvosym, which ships with texlive-fonts-recommended. Font Awesome needs the 1.7 GB texlive-fonts-extra and garbles the same way.
- `semantic` score moved to its own `cvforge[semantic]` extra because sentence-transformers pulls PyTorch. The scoring path is covered by a fake-encoder test; `check` loads the model with `local_files_only` (never downloads) and prints why the score is unavailable and the one-line download command. **Open:** the real model has not run in this container (huggingface.co and download.pytorch.org are blocked); to be verified on the user's machine.
- Density flags: bullets per role or pages above the template's declared limits, and more than 750 words per page.

## Step 7: rewrite

- A rewrite's source is the bullet's text plus the names of the skills that bullet declares; skills declared elsewhere in the profile do not count, so moving "Python" into an unrelated bullet is rejected.
- A rewrite is auto-rejected if it adds a number, number word, month, tool-like token (digits, `#+/.`, inner capitals, all caps), a capitalised name, a word from a built-in tool lexicon, or a word from the profile's skill names or employers. Hyphenated compounds are judged part by part.
- An opening verb from a built-in list of action verbs is allowed even when new; any other new capitalised opening word is rejected.
- Rewrites more than twice the original length (or over 240 characters) are rejected.
- Approval: `--yes` accepts every rewrite that passed; without a TTY or with `--json` and no `--yes`, all are rejected; interactively the user accepts all, picks, or rejects all.
- LiteLLM is imported lazily via importlib, so the base install and mypy never need it. Temperature is 0.
- report.json records every proposal with its status and the facts that caused a rejection.

## Step 8: CI, reusable workflow, README

- `ci.yml` runs ruff, mypy strict and pytest on Python 3.11 and 3.12 with real TeX, then calls the reusable CV workflow on the example profile as a live demo.
- `cv-check.yml` installs cvforge from this repository's `main` by default (`cvforge-spec` input overrides it); there is no `v1` tag yet. Inputs reach shell steps through env vars, never inline expressions.
- `check --json` output drives the job summary and the `badge` output.
- Python 3.11 was verified locally alongside 3.13.


## Review of work order 1 (accepted fixes)

- Parser gating: each adapter has a default `gate`; `[parsers.<name>] gate/enabled` in cvforge.toml overrides it. Defaults: pdftotext, pdfplumber, pypdf-layout gate; pdftotext-layout and pypdf advise.
- `pdftotext -layout` is a separate adapter, advisory. Corpus result: it never separated dates from titles in any template (dates stay on the title's line), but it merges columns in both two-column templates (AltaCV, Deedy), so it stays advisory.
- Fixed text: anything outside `\VAR{}`, `\BLOCK{}` and `\#{}` is fixed by definition; `template validate` lists the visible fixed text of the body separately from filled fields and warns when fixed text looks like a personal fact (email, URL, phone, year).
- Templates may declare `%% engine: pdflatex|xelatex|lualatex`; compile and check use it. Needed by the corpus (Awesome-CV requires LuaLaTeX; Deedy uses fontspec).
- Compile adds the template's folder (recursively) to TEXINPUTS and the font paths, so a template can ship its own .cls, .sty and fonts.
- latexmk output is decoded with `errors="replace"`: TeX splits multi-byte UTF-8 at line wraps (found by the escaper fuzz).

## Work order 2 item 1: corpus and the check rules derived from it

- Corpus: Jake's Resume (MIT), AltaCV (LPPL 1.3+, not MIT as listed: the class header says LPPL), moderncv (LPPL 1.3c), Awesome-CV (LPPL 1.3c) and Deedy Resume (Apache-2.0) as the two-column template. Each built with the sample profile and the full-stack-engineer hat; results in docs/parser-table.md, snapshot in tests/fixtures/templates/results.json.
- Fonts and packages stay as shipped. What TeX Live 2023 lacks (fontawesome6, fontawesome7, Source Sans 3) is installed by `tests/fixtures/templates/provision.sh` from the authors' repositories; moderncv's current class files are bundled in its fixture because TeX Live's copy predates the sample.
- moderncv compiles with LuaLaTeX through the template's own `\ifxetexorluatex` branch: fontawesome7 under pdfLaTeX needs Type 1 maps that cannot be listed without the GitHub API here.
- Rule: matching ignores case. Evidence: AltaCV ("JANE DOE") and Deedy ("ACME SOFTWARE") restyle case in every parser while every letter survives.
- Rule: U+00AD counts as a hyphen. Evidence: Awesome-CV (LuaLaTeX) maps its visible hyphen to U+00AD in every parser, so "end-to-end" failed everywhere while the text was intact.
- Rule: a fact that comes back with inter-word spaces missing ("AcmeSoftware"), aligned to word boundaries, is a warning ("glued"), not a failure. Evidence: pdfplumber on AltaCV, Awesome-CV and Deedy and pypdf on Awesome-CV and Deedy glue words while pdftotext reads the same PDFs with spaces, so the spacing is in the PDF and the gluing is the reader's heuristic. Junk or another word touching the fact, or spaces inserted inside words, still fail.
- Rule: for a bullet (checked by its first eight words) the glued match may run into the ninth word. Evidence: every glued bullet in the corpus failed only at that artificial end boundary.
- Diagnostic (not gating): misses are classed garbled / interleaved / lost; interleaved means the words came back in order with other text between them (merged columns, AltaCV and Deedy). Dates more than a line from their title are counted per parser.
- Kept strict: Jake's Resume loses the underscores of `thai_date_utils` in every parser (OT1 encoding draws `\_` as a rule); that is real damage, so the template fails and the lint now says why.
- Lint added, backed by the corpus: pdfLaTeX with a standard class and no `fontenc` (OT1) — Jake's Resume. Two columns via side-by-side minipages narrower than 0.8 of the text width — Deedy.
- Lint narrowed, backed by the corpus: header/footer warning only when the command has visible content (Jake's empty `\fancyfoot{}` lost nothing); icon-font warning only when icon commands are used in the body (Jake's loads marvosym but uses none and loses nothing); a bare `\hfill` line between boxes is not a right-aligned date (Deedy).
- Lint fixed per research: the fontspec rule accepts `Ligatures=CommonOff` and its fix text says to set NoCommon before `\setmainfont`.
- Not added (research only, no corpus template shows it): microtype letterspacing, fake small caps, Type 3 fonts from missing cm-super.

## Open

- Step 3 (convert the user's own template) waits for the template file.
- Final name: still `cvforge` / Help-me-resume (renaming deferred by the user).
- Semantic score with the real model: see the semantic line above.

## Work order 2 items 4 and 6: goldens and error audit

- Goldens render each corpus template for the sample (with the full-stack-engineer hat) and each fictional person (with their own hat), with `SOURCE_DATE_EPOCH` fixed to 2026-11-01. A corpus-marked test also compiles all 25.
- Command-line usage errors are printed in the same shape as file errors: the "where" is the command (`cvforge add bullet`), the item is the offending argument (`[--weight]`), then the fix. The console script now points at `cvforge.cli:run`, which calls Typer with `standalone_mode=False`; Typer's vendored click exceptions are imported from `typer._click.exceptions` because Typer does not re-export them (pinned by tests/test_errors.py).
- Errors with no line now name the flag or config key that supplied the value (`[--profile]`, `[--template]`, `[--hat]`, `[--job]`, `[TEX]`, `[template]`, `[llm.model]`, `[--locale]`, `[--start]`), and hat validator errors name the offending line. Pydantic's "Value error," prefix is dropped.

## Work order 2 items 5 and 8: fresh install and README

- Quick start installs with `pipx`, not `pip`: Ubuntu 24.04's system Python refuses `pip install` outside a virtual environment (PEP 668), and a first-time user should not need to manage one.
- `install-test.yml` extracts the bash blocks under "## Quick start" and runs them in order on a clean ubuntu-24.04 runner; the one substitution is the `pipx install ...@main` line, which installs the commit under test (`pipx install "$REPO[check]"`). It fails over 10 minutes or without `out/cv.pdf` and a passing `check`.
- README assets are generated by `docs/assets/make_assets.py` from real runs with Pillow. vhs and agg are distributed as GitHub release binaries, which the build environment could not download; the GIF replays the captured output of `init --example`, `build` and `check`.
- The README's template table summarises docs/parser-table.md (three gating readers, one-line cause each); the built-in `minimal` row comes from tests/test_check.py's round-trip test.

## Work order 2 item 3: escaper fuzz

- tests/test_escape_fuzz.py exercises 5,000 strings per run (100 Hypothesis examples x 50 bullets per compiled document, derandomized, no shrinking; a failing batch is bisected to the failing strings). Each must build, compile, keep every `% id:` and survive pdftotext with its letters and digits intact.
- Fixed from its findings (295 of 5,000 failed before): latexmk output decoding; `[`/`]` escaped as `{[}`/`{]}` (a leading bracket became `\item`'s optional argument); stretchable break points in long bullet tokens (a bare `\allowbreak` has no glue, so lines still overflowed); the traceability split ignores an escaped `\%`; traceability now matches each bullet on its own `% id:` line, so repeated or overlapping bullet text no longer fails the build, and its errors name the output .tex.
- Break points go only into bullet text: templates reuse email and link text inside URLs (`mailto:`, GitHub user names), where a break command would corrupt the link.
- Known limit, kept as strict xfail: pdfLaTeX with T1 and lmodern cannot typeset some letters (Ħ, ŉ, Greek) and extracts others wrongly (Đ as Ð, comma-below letters with a detached comma). That is font coverage, not escaping; a XeLaTeX or LuaLaTeX template with a Unicode font handles them.

## Work order 3, step 0: fourth and fifth readers

- Added `pdfminer` (pdfminer.six `high_level.extract_text`, the call Resume Matcher, markitdown and pyresparser make) and `pdfium` (pypdfium2) as advisory readers, as the user decided. PDFium's CRLF line ends and its U+FFFE line-end hyphen marker are normalised in the adapter.
- Corpus result: pdfminer and pdfium read AltaCV and Deedy without loss, where pdfplumber's default `extract_text()` interleaves and glues; both still lose Jake's underscores (OT1). Advisory for now; promoting pdfminer to gating is a candidate decision for the user.
- `v0.1.0` exists as a local tag on 20d62da; this session's git access does not push tags.
