# Parser table

Every corpus template built with `examples/profile.cv.txt` and the
`full-stack-engineer` hat, compiled, and read back by every parser adapter. Generated
by `python -m tests.corpus --write`; `tests/test_corpus.py` fails if a fresh run
disagrees with this table.

✓ means every fact came back as whole words. ✗ lists what was lost: *garbled* (something
close came back), *interleaved* (the words came back with other text between them, i.e.
merged columns) or *lost*. *glued N* counts facts that came back with inter-word spaces
missing; *dates apart* counts role dates more than a line away from their title. Both
are warnings, not failures.

| Template | pdftotext (gate) | pdftotext-layout (advisory) | pdfplumber (gate) | pypdf-layout (gate) | pypdf (advisory) | pdfminer (advisory) | pdfium (advisory) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [Jake's Resume](https://github.com/jakegut/resume) | ✗ 1 garbled: name `thai_date_utils` → `date utils` (dates apart 2/2) | ✗ 1 garbled: name `thai_date_utils` → `date utils` | ✗ 1 garbled: name `thai_date_utils` → `date utils` | ✗ 1 garbled: name `thai_date_utils` → `date utils` | ✗ 3 garbled: title `Technical Writer` → `T echnical W riter`; title `Junior Full-Stack Develo` → `Junior F ull-Stack Developer`; +1 more | ✗ 1 garbled: name `thai_date_utils` → `date utils` (dates apart 2/2) | ✗ 1 garbled: name `thai_date_utils` → `date utils` |
| [AltaCV](https://github.com/liantze/AltaCV) | ✓ (dates apart 2/2) | ✗ 1 interleaved: degree `B.Eng. Computer Innovati` → `B.Eng. Computer Innovation •` (dates apart 2/2) | ✗ 2 garbled/interleaved: phone `+66 80 000 0000` → `�+66800000000`; degree `B.Eng. Computer Innovati` → `B.Eng. Computer Innovation •` (glued 24) | ✗ 3 garbled/interleaved: degree `B.Eng. Computer Innovati` → `B.Eng. Computer Innovation •`; skill `REST APIs` → `ActionsPostgreSQLTypeScriptR`; +1 more (dates apart 2/2) | ✗ 4 garbled: title `Technical Writer` → `T echnical Writer`; bullet `Typeset the printed API ` → `Typeset the printed API refe`; +2 more (dates apart 1/1) | ✓ (dates apart 2/2) | ✓ (dates apart 2/2) |
| [moderncv (contemporary)](https://github.com/moderncv/moderncv) | ✓ (dates apart 2/2) | ✓ | ✓ | ✗ 5 garbled: phone `+66 80 000 0000` → `MOBILE-ANDROID-ALT+66 80 000`; start `Jun 2025` → `2025Jun 2025-Present`; +3 more (dates apart 2/2) | ✓ | ✓ (dates apart 2/2) | ✓ |
| [Awesome-CV](https://github.com/posquit0/Awesome-CV) | ✓ | ✓ | ✓ (glued 26) | ✓ (glued 22) | ✓ (glued 22) | ✓ (dates apart 2/2) | ✓ |
| [Deedy Resume (OpenFonts)](https://github.com/deedydas/Deedy-Resume) | ✓ (dates apart 1/2) | ✗ 1 interleaved: degree `B.Eng. Computer Innovati` → `B.Eng. Computer Innovation J` | ✗ 1 garbled: degree `B.Eng. Computer Innovati` → `B.Eng. ComputerInnovation Ju` (glued 28) | ✗ 1 interleaved: degree `B.Eng. Computer Innovati` → `B.Eng. Computer Innovation J` (glued 12) | ✗ 3 garbled: bullet `Typeset the printed API ` → `Typeset the printed API refe`; skill `Technical documentation` → `T echnicaldocumentation`; +1 more (glued 1) | ✓ | ✓ (glued 1) |

## Templates

| Template | Licence | Layout | Lint warnings |
| --- | --- | --- | --- |
| Jake's Resume | MIT | one column; dates right-aligned with tabular*; OT1 font encoding (no fontenc) | pdfLaTeX with the default OT1 font encoding; right-aligned dates may separate from titles in some parsers (\hfill, \extracolsep{\fill} or similar). |
| AltaCV | LPPL 1.3 or later (class header; the work order listed MIT) | two columns (paracol); Font Awesome icons in contact line and event headers | two-column layout |
| moderncv (contemporary) | LPPL 1.3c | dates in a left margin column; icons in contact block; compiled with LuaLaTeX | fontspec without Ligatures=NoCommon |
| Awesome-CV | LPPL 1.3c | one column, tabular* rows with right-aligned dates; Font Awesome 6; LuaLaTeX | none |
| Deedy Resume (OpenFonts) | Apache-2.0 | two columns (side-by-side minipages); upper-cased headings; Lato and Raleway | two-column layout |
