# Deedy Resume (OpenFonts version)

- Source: https://github.com/deedydas/Deedy-Resume (`OpenFonts/deedy-resume-openfont.cls` and
  the bundled Lato and Raleway fonts, fetched 2026-11-01 from
  https://raw.githubusercontent.com/deedydas/Deedy-Resume/master/OpenFonts/)
- Licence: Apache-2.0; full text in `LICENSE`. Lato and Raleway are SIL Open Font Licence fonts
  as bundled by the project (the licence text is embedded in each font file).
- The sample `.tex` could not be fetched: its path is not guessable without the GitHub API,
  which this environment blocks. `template.tex` is written against the class's own macros
  (`\namesection`, `\runsubsection`, `\descript`, `\location`, `tightemize`, `\sectionsep`) in
  the published layout: a 0.33 and a 0.66 text-width minipage side by side, including the
  sample's `\vspace{\topsep}` after `\location`.
- Fonts are loaded by the class from `fonts/lato/` and `fonts/raleway/` relative paths, as
  published; cvforge's compile step adds the template folder to the font search path.
