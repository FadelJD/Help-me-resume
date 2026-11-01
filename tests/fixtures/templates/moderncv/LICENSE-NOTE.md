# moderncv

- Source: https://github.com/moderncv/moderncv (`template.tex`, `moderncv.cls` and the style,
  body, head, colour and icon files it loads, fetched 2026-11-01 from
  https://raw.githubusercontent.com/moderncv/moderncv/master/)
- Licence: LaTeX Project Public License 1.3c (README, section "Licence"). Files in `original/`
  are unmodified.
- Why the class files are bundled: the current `template.tex` uses the `contemporary` style and
  `cerulean` colour, which TeX Live 2023's moderncv lacks, and the current class loads
  `fontawesome7` (installed by `../provision.sh`).
- Engine: LuaLaTeX. The template supports it through its own `\ifxetexorluatex` branch (Latin
  Modern via fontspec). Under pdfLaTeX, fontawesome7 would need Type 1 font maps that could not be
  installed here.
- `template.tex`: header block added; class options, style, colour, geometry and fonts are the
  original's. The sample has no projects section, so projects are left out. Removed as
  sample-only: `\born`, extra phones, social ids, photo, quote, thesis, languages, skill matrix
  and publications. Links go in `\extrainfo` as full links.
