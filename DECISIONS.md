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

## Work order 3: import and checking existing PDFs

- `cvforge import FILE...` drafts a profile from PDFs (`pdftotext -layout` keeps a row's left and right parts on one line; link targets come from the PDF's annotations) or LaTeX (Jake's Resume family macros and the header). Deterministic heuristics, no model. Several files merge: union of facts, earlier files take precedence, text compared after NFKC, straight quotes, plain dashes, case and spacing; disagreements and second wordings (word similarity >= 0.5) go to CONFIRM.md and the profile keeps the first file's value marked `# TODO confirm`.
- Imported bullets get `skills:` only where a declared skill name appears verbatim (case-sensitive, whole term); `weight: 3` is written as a default and labelled as not from the files.
- Profile schema gained what real CVs need without guessing: year-only dates (`2021`), `education.location`, `projects.stack` (the tools line under a project) and `skill_groups` (the CV's own grouping; a hat's groups override it). Template features `education.location` and `projects.stack` expose the new fields.
- `skills = "all"` in cvforge.toml lists every declared skill in the profile's order and groups; the default `evidenced` keeps showing only skills a shown bullet demonstrates. The evidence score is reported either way.
- Roles are ordered by start date, then end date, most recent first (was end date first): equally common, and it keeps CVs that list an overlapping later-ending role below a later-starting one in their own order.
- `cvforge check FILE.pdf --profile P` checks a PDF that cvforge did not build against a profile's facts (no compile); used for baselines of existing CVs.
- Bullets only a later file has, and entries only a later file has, are kept (union of facts) but each gets a CONFIRM.md entry asking whether it is a separate fact. Two wordings are detected by word-order similarity >= 0.5 or, for reworded bullets with abbreviations, by sharing at least half the content words of the shorter one; the same question raised by several files becomes one entry.

## Work order 3 step 7: engine detection

- `build --compile` and `check` detect the engine when the template declares none: LuaLaTeX if the preamble or a local class requires it; XeLaTeX then LuaLaTeX if fontspec-family packages load unconditionally; pdfLaTeX first with LuaLaTeX and XeLaTeX as fallbacks if the preamble supports several engines; pdfLaTeX otherwise. Local .cls/.sty files next to the template are read too. A declared `%% engine:` is used as is. The build line names the engine and why; a failure stays one line naming the .tex line, plus the engines tried.
- Corpus result with every `%% engine:` line removed: Jake's and AltaCV pdfLaTeX; Awesome-CV LuaLaTeX (its class requires it); Deedy XeLaTeX (fontspec in its class); moderncv falls back from pdfLaTeX to LuaLaTeX, since fontawesome7 has no Type 1 fonts here.
- Fixed a conversion bug found by building without a hat: the Awesome-CV fixture emitted `\position{}` with an empty title, which the class cannot typeset; the line is now conditional (rendered output with a title is unchanged).

## Work order 4: Windows support

- Branch note: `main` did not yet contain work order 3's tool commits (engine detection, PDFium and pdfminer readers, import). `wo4-windows` was created from `main` and those four tool-only commits were cherry-picked from `wo3-user-cv` (no file under private/, blocklist scan clean), because steps 1 and 2 build on them.
- Step 1: compile runs latexmk only when it is on PATH; otherwise the engine itself, with `-interaction=nonstopmode -halt-on-error -file-line-error -output-directory`, two passes and a third when the .aux changed between them. `CVFORGE_NO_LATEXMK=1` forces the direct runs (used by tests). A missing engine is one line naming the engine and pointing at `cvforge doctor`.
- Direct runs exposed log wrapping: TeX breaks log lines at 79 characters, which cut the error message ("Undefin"). compile sets `max_print_line=10000` (TeX Live honours it) and unwraps 79-character lines before parsing (MiKTeX ignores the variable).
- The `tex` test marker now needs pdfLaTeX, not latexmk; a new `poppler` marker covers tests that call pdftotext directly, so a Windows run without poppler skips exactly those and says why.
- Verified on Linux with latexmk removed from PATH (a PATH that links every /usr/bin program except latexmk): full suite including the corpus, 357 passed, 5 xfailed.
- Step 2: the gate set is per OS (`parsers.DEFAULT_GATES`): Linux and macOS gate pdftotext, pdfplumber and pypdf-layout; Windows gates pdfplumber, pypdf-layout and pdfium (pypdfium2, a pip dependency), with pdftotext advisory when present. pdfminer is advisory everywhere. `[parsers.<name>]` overrides still apply.
- A reader that is not installed is reported as "not installed" with the install command for the detected OS (`cvforge/platforms.py`), never skipped silently. A missing gating reader is an error and fails the check (the badge counts it: `parsed: 2/3`); a missing advisory reader is a warning. The report lists `gates` and `gates_missing`.
- The corpus snapshot (results.json) is the Linux reference; its comparison test skips on other systems with that reason. The parser table now states the per-OS gate sets; its pdfium column shows the Windows gate's behaviour on the corpus.
- Windows package ids in platforms.py (winget MiKTeX.MiKTeX, oschwartz10612.Poppler, Python.Python.3.12, StrawberryPerl.StrawberryPerl; scoop miktex, poppler; choco miktex, poppler) are unverified: there is no Windows machine in this environment.
- Step 3: every external program goes through `platforms.run_tool`: an argument list (`shell=False`), an explicit working folder (the file's folder), UTF-8 decoded with `errors="replace"`, a timeout. Tests decode the same way. No code path uses /tmp; tests use pytest's `tmp_path`, workflows `$RUNNER_TEMP`.
- `page_count` falls back to pypdf when poppler's pdfinfo is absent (Windows), so the density check keeps a page count.
- CRLF: files are read with Python's universal newlines, and the profile parser and template header reader also normalise `\r\n` for text passed in directly. A test builds from CRLF copies of the sample profile, hat and template and requires output identical to the LF build.
- Unverified on Windows: kpathsea's recursive `dir//` search in TEXINPUTS/OPENTYPEFONTS (used for templates that ship their own .cls or fonts) is documented for TeX Live on Windows; MiKTeX may need the template folder registered as a root instead.
- Step 4: `cvforge doctor` prints one line per item (system, Python 3.11+, a TeX engine, latexmk, each reader, the semantic model) as OK or MISSING with the install command for the detected OS, and exits 1 if Python, the engine or a gating reader for this OS is missing. Optional items never change the exit code. `init` and `build` print "run cvforge doctor" when a required tool is absent (and before a failed build's error).
