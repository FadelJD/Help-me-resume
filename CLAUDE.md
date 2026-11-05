# CLAUDE.md

Read `STATUS.md` first: branches, open PRs and what is unverified.

Full build spec: `docs/SPEC.md`. Decisions not covered by the spec: `DECISIONS.md` (one line each).

The tool turns `profile.cv.txt` into a `.tex` CV built on the user's own LaTeX template, then proves the
PDF survives automated screening. Python 3.11+, one package, one Typer CLI.

## Design principles (refuse any design that breaks one)

1. **Deterministic first, LLM last.** Parsing, validation, selection, ranking and rendering run with no
   network and no model. Only `tailor --rewrite` calls an LLM; a correct `.tex` must be produced without it.
2. **One source of truth.** Everything about the person lives in `profile.cv.txt`. Hats, job ads and
   templates never carry facts about the person.
3. **Every output line is traceable.** Each bullet in the `.tex` carries `% id:exp-03.b2`. A line with no
   id cannot be emitted.
4. **The LLM may reword and reorder, never add.** A rewrite introducing a number, tool, employer or date
   not in the source item is rejected automatically. When unsure, treat it as adding and reject.
5. **Template is a contract, not a guess.** Templates declare supported placeholders in a header block;
   the tool validates before rendering and reports what it will and will not fill.
6. **Verified, not assumed.** `check` compiles the PDF, runs real parsers, and fails on lost or garbled fields.

## Working rules

- Run `ruff check`, `ruff format --check`, `mypy --strict cvforge` and `pytest` before every commit. Fix, do not suppress.
- Errors name the file, the line or item id, and the fix. "Invalid profile" is not acceptable.
- Dependency direction: `cli` -> `select`/`rewrite`/`template`/`check` -> `schema`. Nothing imports `cli`.
  `parse.py` is the only module that knows the text format.
- Never put the user's real profile in `examples/` or `tests/fixtures/`. Sample data is fictional.
- Follow the build order in `docs/SPEC.md`; each step ends with passing tests and a commit.

## Branches

- `main`: released, tagged versions only.
- `develop`: integration branch; feature work merges here via PR.
