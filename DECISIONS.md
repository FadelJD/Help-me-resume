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
- `templates/minimal.tex` puts dates inline, not right-aligned with `\hfill`: pdftotext split right-aligned dates away from their title in testing.
- Traceability is enforced twice: statically (bullet text and `% id:` on the same template line) and after render (each output line holding bullet text carries the matching id).
- Selection result types live in `schema.py` as dataclasses, so `template.py` depends only on `schema`.
- `build_date` honours `SOURCE_DATE_EPOCH` for reproducible output.
- `views.py` holds rich terminal rendering so `cli.py` stays thin.
- BM25 is implemented in `score.py` (about 30 lines) instead of `rank-bm25`, which pulls numpy; `build --job` stays dependency-free and offline.
- TeX system packages for dev and CI: texlive-latex-base, texlive-latex-extra, texlive-fonts-recommended, lmodern, latexmk, poppler-utils.
