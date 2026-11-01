# Decisions

Choices the spec leaves open. One line each, newest last.

- Repo root is the package root (spec's outer `cvforge/` folder = this repo); the Python package lives in `cvforge/`.
- Package and CLI keep the placeholder name `cvforge` until a final name is chosen; renaming is a mechanical find/replace.
- Branching: `main` holds releases, `develop` is the integration branch, feature branches merge into `develop` by PR.
- Build tooling: `uv` with a `hatchling` backend; `pip install -e ".[dev]"` also works.
