# Awesome-CV

- Source: https://github.com/posquit0/Awesome-CV (`awesome-cv.cls`, `examples/resume.tex`,
  `examples/resume/experience.tex`, `examples/resume/education.tex`, fetched 2026-11-01 from
  https://raw.githubusercontent.com/posquit0/Awesome-CV/master/)
- Licence: LaTeX Project Public License 1.3c; full text in `LICENCE`. Files in `original/` are
  unmodified.
- Engine: LuaLaTeX, which the class requires (`Class awesome-cv Error: LuaLaTeX is required`).
- Fonts: Source Sans 3, Roboto and Font Awesome 6, exactly as the class loads them;
  `../provision.sh` installs the ones TeX Live 2023 lacks.
- `template.tex`: header block added; class, geometry, colours and header separator are the
  original's. Removed as sample-only: summary, honors, certificates and quote. Skills use the
  class's own `cvskills` environment. GitHub and LinkedIn links are passed as user names, which
  is what the class's `\github`/`\linkedin` expect.
