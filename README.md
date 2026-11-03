# CV Forge

Build your CV from one plain-text profile on a LaTeX template you choose, then prove that screening software can read it back.

![init, build and check in a terminal](docs/assets/quickstart.gif)

## Why this exists

Most CVs are read by software before a person sees them: an applicant tracking system, which this page calls screening software from here on. LaTeX CVs look sharp but often come out garbled when that software pulls the text out of the PDF, losing dates, names and whole bullet points. CV Forge builds your CV from a single profile and then checks, with the same open-source readers screening software uses, that every fact reads back correctly.

It is an open source CV builder for people who want an ATS-friendly resume they can keep as CV as code, and a JSON Resume alternative that targets LaTeX.

## Install

Each block ends with `cvforge doctor`, which checks Python, a TeX engine and the PDF readers, and prints the exact install command for anything missing.

### Windows

In PowerShell:

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id Git.Git
winget install -e --id MiKTeX.MiKTeX
py -m pip install --user pipx
py -m pipx ensurepath
# Close and reopen PowerShell so the new PATH applies, then:
py -m pipx install "cvforge[check] @ git+https://github.com/FadelJD/Help-me-resume"
cvforge doctor
```

If you prefer TeX Live to MiKTeX, install it from [tug.org/texlive/windows.html](https://tug.org/texlive/windows.html) instead. MiKTeX downloads LaTeX packages the first time a CV needs them. If it asks every time, turn on automatic installs in the MiKTeX Console, under Settings.

On Windows, pdftotext is not a gate unless poppler is installed (`winget install oschwartz10612.Poppler`). Without poppler, `check` gates on pdfplumber, pypdf-layout and PDFium, which all come with `pipx install`. pdftotext uses the same library as many applicant tracking systems, so the Windows result says less about those systems than the Linux one. Install poppler, or run `check` in WSL, for the Linux gate set. pdftotext then also runs, as an advisory reader.

### Ubuntu or Debian

```bash
sudo apt-get update && sudo apt-get install -y latexmk texlive-latex-extra texlive-fonts-recommended lmodern poppler-utils pipx
pipx install "cvforge[check] @ git+https://github.com/FadelJD/Help-me-resume"
cvforge doctor
```

### WSL

In a WSL Ubuntu terminal, follow the Ubuntu or Debian block above, which ends with `cvforge doctor`.

If a terminal says `cvforge: command not found`, run `pipx ensurepath` and open a new terminal. On macOS, install [MacTeX](https://tug.org/mactex/), poppler and pipx with Homebrew, then follow the Ubuntu block from `pipx install`. CI does not test macOS. On Windows, CI runs the block above on a hosted windows-latest runner, with TeX Live and without poppler or latexmk. There, the example CV builds and passes `check`, while 14 of the unit tests still fail. Nobody has run it on a Windows PC yet. [docs/windows.md](docs/windows.md) lists what is verified and what is not.

## Quick start

The same commands work in bash and PowerShell:

```bash
mkdir my-cv
cd my-cv
cvforge init --example
cvforge build --compile -o out/cv.tex
cvforge check out/cv.tex
```

You now have a PDF and a report: `out/cv.pdf` and `out/cv.report.json`. The example is a fictional person, Jane Doe. To start your own, run `cvforge init` in an empty folder and answer the questions.

## Does your template survive screening software?

We converted five popular public LaTeX CV templates and built the same CV with each. Then we read every PDF back with three readers, the software that reads your PDF inside screening tools. ✓ means every name, title, employer, date, bullet and skill came back intact.

| Template | pdftotext | pdfplumber | pypdf | What went wrong |
| --- | --- | --- | --- | --- |
| CV Forge `minimal` (built in) | ✓ | ✓ | ✓ | Nothing. |
| [Awesome-CV](https://github.com/posquit0/Awesome-CV) | ✓ | ✓ | ✓ | Passes. Two readers drop some spaces between words (`AcmeSoftware`). |
| [moderncv](https://github.com/moderncv/moderncv) | ✓ | ✓ | ✗ | pypdf glues the year column and icon names onto dates and the phone number. |
| [Deedy Resume](https://github.com/deedydas/Deedy-Resume) | ✓ | ✗ | ✗ | Two columns: a wrapped degree picks up words from the other column. |
| [AltaCV](https://github.com/liantze/AltaCV) | ✓ | ✗ | ✗ | Two columns merge, and an icon glyph is glued to the phone number. |
| [Jake's Resume](https://github.com/jakegut/resume) | ✗ | ✗ | ✗ | Underscores vanish (`thai_date_utils` reads as `thai date utils`): the default font encoding draws `_` as a line. One line fixes it: `\usepackage[T1]{fontenc}`. |

![Awesome-CV built by CV Forge, with its check summary](docs/assets/cv-check.png)

pypdf here runs in layout mode. Its default mode, used by many quick screening scripts, splits words at letter pairs in every LaTeX font we tried (`T echnical W riter`), so CV Forge reports it as a warning rather than a failure. Two more readers run as advisers: pdfminer's high-level call, which Resume Matcher and similar tools use, and PDFium, the engine in Chrome. pdfminer reads both two-column templates cleanly where pdfplumber does not. The full table, with every reader and every lost string, is in [docs/parser-table.md](docs/parser-table.md). A test rebuilds it, so it cannot go stale. This is a resume parser test you can run on your own template.

## One profile, many CVs

Everything about you lives once in `profile.cv.txt`. A *hat* says which skills matter for a kind of role. A job ad then decides which bullets lead. Same person, same hat, two job ads, two different orders. This is the fictional backend developer from [examples/people](examples/people), most recent role:

| Ad: API platform | Ad: infrastructure |
| --- | --- |
| 1. Designed a public REST API in Go with OpenAPI 3 specs… | 1. Migrated 22 services from VMs to Kubernetes on Terraform-managed AWS… |
| 2. Introduced gRPC between internal services, reducing p99 latency… | 2. Designed a public REST API in Go with OpenAPI 3 specs… |
| 3. Migrated 22 services from VMs to Kubernetes… | 3. Introduced gRPC between internal services… |
| 4. Built Prometheus alerting and SLO dashboards… | 4. Built Prometheus alerting and SLO dashboards… |

See why with `cvforge explain`. It prints each bullet's score: its own weight, times the hat's weight for its skills, times how well it matches the ad. Nothing is written until you run `build`. The full outputs are saved in [examples/people/backend-developer/explain](examples/people/backend-developer/explain). One CV, many jobs, and the facts never change between them.

## Bring your own LaTeX

Your template keeps its fonts, packages and layout. You mark the spots CV Forge fills.

1. Put these lines at the very top of your `.tex` file, keeping only the sections it has:

   ```latex
   %% cvforge-template v1
   %% sections: experience, projects, skills, education
   %% supports: person.links, person.phone
   %% max-bullets-per-role: 5
   ```

2. Replace your own details with placeholders. `\VAR{person.name}` prints your name. A loop repeats a block for every role:

   ```latex
   \BLOCK{for job in experience}
   \textbf{\VAR{job.title}} \hfill \VAR{job.start} -- \VAR{job.end}\\
   \begin{itemize}
   \BLOCK{for b in job.bullets}
     \item \VAR{b.text} % id:\VAR{b.id}
   \BLOCK{endfor}
   \end{itemize}
   \BLOCK{endfor}
   ```

   Every bullet line ends with `% id:\VAR{b.id}`, so each line in your CV points back to the profile line it came from.

3. Run `cvforge template validate my.tex`. It lists the fields it will fill, the text it will leave exactly as you wrote it, and any layout known to confuse screening software. Then build with `cvforge build --template my.tex --compile`.

Anything outside `\VAR{}` and `\BLOCK{}` is printed as written. [templates/minimal.tex](templates/minimal.tex) is a complete example, and the five converted templates in [tests/fixtures/templates](tests/fixtures/templates) show the same steps on real designs.

## How the check works

`cvforge check` compiles your PDF and tests it in three layers.

**Reads.** Screening software first turns your PDF into plain text. CV Forge does the same with pdftotext, pdfplumber and pypdf, and looks for every fact it put in: your name and contact details, each title, employer and date, the first eight words of each bullet, and every skill. A fact that comes back broken, merged with the other column, or stuck to an icon fails the check and is named, with what came back instead.

**Matches.** Many systems still compare the words in your CV with the words in the job ad. Give `check` the ad with `--job` and it reports how much of the ad's vocabulary your CV covers, and the important terms it is missing. An optional local language model adds a similarity score; it never sends your CV anywhere.

**Judges.** Newer screening software reads the whole CV and asks whether each claimed skill is shown in your experience. CV Forge only lists a skill when a bullet it printed shows it, and reports the share as *evidence*. It should be 100%.

Scores are reported, not enforced, unless you pass `--strict`. The check never claims a score for a named commercial product, because nobody outside the vendor can reproduce one.

## Honest by design

CV Forge may reword and reorder your bullets, but it never adds a number, tool, employer or date that is not already in your profile, and every printed line points back to its source. That matters because screening software now compares CVs with LinkedIn and GitHub, and an invented claim is easier to spot than ever.

The optional rewording step uses a language model you choose, shows you every change, and automatically rejects any rewrite that adds a fact.

## For students

1. Run `cvforge init` and answer the questions: contact details, then each job, project or degree, one line at a time.
2. Build with `cvforge build --compile -o out/cv.tex` and open `out/cv.pdf`.
3. Run `cvforge check out/cv.tex` before you send it.
4. Add new experience later with `cvforge add bullet`, without opening the file.

## For developers

1. Keep `profile.cv.txt`, your template and `hats/` in a Git repository: your CV as code.
2. Every bullet carries an id, so a diff shows exactly which fact changed.
3. Add `--json` to any command for scripts and agents.
4. Add the GitHub Action below so every push rebuilds the PDF and fails if a fact stops reading back.

## For career-changers

1. Keep every role and bullet in one profile, including the ones you will not always show.
2. Make one hat per direction, for example `hats/developer.toml` and `hats/technical-writer.toml`.
3. Build per application: `cvforge build --hat technical-writer --job ad.txt --compile`.
4. Run `cvforge explain` with the same options to see which bullets led and which were dropped.

## Add it to your CV repo

Add this file to your CV repository as `.github/workflows/cv.yml`:

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

Each push builds your CV, compiles it, runs the check and attaches the PDF and report to the run. The summary line, for example `parsed: 3/3 · keyword: 0.71 · evidence: 100%`, reads like this. *parsed* is how many readers returned every fact. *keyword* is how much of the job ad's vocabulary you cover. *evidence* is the share of listed skills shown in your experience.

## Roadmap

A Typst renderer, DOCX and plain-text export, an MCP server so AI agents can run the build-and-check loop, cover letters with the same no-invented-facts rule, and a gallery of templates that pass the check. Not planned: a web app, accounts, job scraping or auto-apply.

## Contributing

Read [CLAUDE.md](CLAUDE.md) for the design rules and [docs/SPEC.md](docs/SPEC.md) for the full specification. Choices the spec leaves open are logged one line each in [DECISIONS.md](DECISIONS.md). Before a pull request, run:

```bash
pip install -e ".[dev,check]" && ruff check . && mypy cvforge && pytest -q
```

To add a template to the table, follow [tests/fixtures/templates](tests/fixtures/templates) and run `python -m tests.corpus --write`. Error messages must name the file, the line or item, and the fix; [docs/errors.md](docs/errors.md) lists them all.

## Licence

MIT. The converted templates in `tests/fixtures/templates` keep their own licences, noted in each folder.
