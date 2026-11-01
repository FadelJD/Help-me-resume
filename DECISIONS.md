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
