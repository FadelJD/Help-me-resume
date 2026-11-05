# Status

Last updated: 2026-11-05. Every session ends by updating this file as its final commit.

## Branches

| Branch | Head | State | Next action |
| --- | --- | --- | --- |
| `main` | 09af8d1 | Release 0.2.0 | Push the tags (below). |
| `develop` | 09af8d1 | Same as main | Merge PR #6 after review. |
| `wo5-finish` | see PR #6 | Work order 5: confirm, PDF import without poppler, LLM features, DOCX, README, this file | Review PR #6; CI is its test run. |
| `wo3-user-cv` | 6746438 | Parked: your real CVs live in git-ignored `private/` | Answer `private/CONFIRM.md` with `cvforge confirm -p private/profile.cv.txt`. Then cherry-pick only the import command and the sample-data fix to develop. Never merge the branch. |

## Open pull requests

- [#6](https://github.com/FadelJD/Help-me-resume/pull/6) `wo5-finish` into `develop`: not merged.

## Not verified yet, and how to verify it

| What | Command |
| --- | --- |
| Tags v0.1.0 and v0.2.0 are not on GitHub (this session cannot push tags) | `git fetch origin && git tag -a v0.1.0 20d62da -m "CV Forge v0.1.0" && git tag -a v0.2.0 09af8d1 -m "CV Forge v0.2.0" && git push origin v0.1.0 v0.2.0` |
| LLM features with a real model and key (only canned responses have run) | `pipx inject cvforge litellm && CVFORGE_LLM_PROVIDER=anthropic CVFORGE_LLM_MODEL=claude-sonnet-5-5 CVFORGE_LLM_API_KEY=<your key> cvforge tailor --job examples/job.txt -p examples/profile.cv.txt -t templates/minimal.tex --hat examples/hats/developer.toml --rewrite -o out/llm.tex` |
| Windows on a real PC (only the hosted CI machine has run it) | In PowerShell, after the README's Windows block: `cvforge doctor; mkdir my-cv; cd my-cv; cvforge init --example; cvforge build --compile --docx -o out/cv.tex; cvforge check out/cv.tex` |
| The built PDF and DOCX as a person sees them (only readers have checked them) | After the Quick start: open `my-cv/out/cv.pdf` and `my-cv/out/cv.docx` |
| MiKTeX, macOS, Windows PowerShell 5.1 | Not tested anywhere; see docs/windows.md |
| Work order 5's later items (tag, llm-reader, DOCX, confirm merged together) | The CI run on PR #6 |
