# Research: extractors used by screeners, and LaTeX settings that break extraction

Work item 7. Two questions: (A) which PDF text extractors public screening and resume-parsing projects
actually call, and whether CV Forge needs a fourth adapter; (B) which LaTeX font and package settings are
known to break extraction, as candidates for `template.lint`.

Method. Project sources were read from `raw.githubusercontent.com` (github.com HTML, the GitHub API,
tex.stackexchange.com, ctan.org, tug.org and readthedocs were blocked by the network proxy; claims that rest
only on a search-result snippet are marked *(snippet)*). Every Question B row was also reproduced locally:
small `.tex` files compiled with pdfTeX 1.40.25 / XeTeX / LuaHBTeX 1.17 (TeX Live 2023, Debian; cm-super
**not** installed) and read with poppler `pdftotext` 24.02 (raw and `-layout`), pdfplumber 0.11.10,
pdfminer.six 20260107 `high_level.extract_text`, pypdf 6.17 and pypdfium2 5.13 (PDFium). The scratch
scripts are not in the repo; quoted outputs below are verbatim (`repr`).

## Question A: extractors used by screening projects

| Project | Extractor | Evidence |
|---|---|---|
| OpenCATS (PHP ATS) | poppler `pdftotext -layout` (antiword for .doc) | `lib/DocumentToText.php` builds `PDFTOTEXT_PATH -layout file -` [1] |
| Resume Matcher (srbhr) | markitdown, i.e. pdfminer.six (plus pdfplumber for form-like pages); pypdf only as a "non-blank render" probe | `apps/backend/pyproject.toml` and `requirements.txt` pin `markitdown[docx,pdf]`, `pdfminer.six`; `pypdf` commented as render probe [2][3]; `app/services/parser.py` imports `MarkItDown` and pdfminer [4] |
| markitdown (Microsoft, used by Resume Matcher) | pdfplumber `page.extract_text()` when any page looks like a form/table, otherwise **`pdfminer.high_level.extract_text`**; pdfminer is also the fallback | `_pdf_converter.py` [5]; `pyproject.toml` `pdf` extra = pdfminer.six + pdfplumber [6] |
| OpenResume (xitanggg) | Mozilla **pdf.js** (`pdfjs-dist`, `page.getTextContent()`) in the browser | `package.json` [7]; `src/app/lib/parse-resume-from-pdf/read-pdf.ts` [8] |
| pyresparser (OmkarPathak, PyPI) | pdfminer.six (`PDFPageInterpreter` + `TextConverter`, `LAParams`) | `requirements.txt` pins `pdfminer.six==20181108` [9]; `pyresparser/utils.py` [10] |
| LangChain community loaders (LLM screening demos) | `PyPDFLoader` = pypdf (the usual tutorial default); also `PDFMinerParser`, `PDFPlumberParser`, `PyMuPDFParser`, `PyPDFium2Parser` | `langchain_community/document_loaders/parsers/pdf.py` [11] |
| LlamaIndex `PDFReader` | pypdf | `readers/file/docs/base.py` [12] |
| Apache Tika | Apache PDFBox (Java) | `tika-parser-pdf-module/pom.xml` depends on `org.apache.pdfbox:pdfbox` [13] |
| Unstructured | pdfminer.six (+ pypdf, pikepdf; layout models via unstructured-inference) | `pyproject.toml` PDF/image extra [14] |
| Docling (IBM) | own `docling-parse` or pypdfium2 (PDFium) backends | `pyproject.toml` `format-pdf-pypdfium2`, `docling-parse` [15] |

Engines in that list, by codebase lineage: **poppler** (xpdf-derived C++), **pdfminer.six** (Python),
**pypdf** (Python), **pdf.js** (JavaScript), **PDFBox** (Java), **PDFium** (C++, Foxit-derived, used by
Chrome), **MuPDF** (C). CV Forge covers the first three.

### Two findings about the current adapters

1. **pdfplumber's default `extract_text()` is not what pdfminer.six users see.** pdfplumber groups words
   with an absolute `x_tolerance=3` pt; `pdfminer.high_level.extract_text` (markitdown's normal path,
   pyresparser, Unstructured) uses a relative `word_margin` [23]. On ordinary body text with tightly spaced
   fonts the two disagree:
   - libertine, ebgaramond, fourier, kpfonts: pdfplumber `'Officeefficientfluentworkflow.Müllerrésumé.'`;
     pdfminer high-level `'Office efficient fluent workflow. Müller résumé.'`.
   - microtype-letterspaced small caps: pdfplumber `'Senior Software Engineer'`; pdfminer high-level
     `'S e n i o r S o f t wa r e E n g i n e e r'`.

   So `DECISIONS.md` ("markitdown ... pdfminer underneath, the same engine as pdfplumber ... would not add
   an independent reading") holds for the engine but not for the output. A `pdfminer` adapter calling
   `pdfminer.high_level.extract_text` would read differently from `pdfplumber` and costs no new dependency.
2. **PDFium is already installed.** pdfplumber depends on `pypdfium2` [21], so PDFium ships with
   `cvforge[check]` today.

### Fourth-adapter recommendation

- **Add PDFium via `pypdfium2` as the fourth engine (advisory at first).** It is an independent codebase
  from poppler, pdfminer and pypdf, is used by Chrome, Docling and LangChain's `PyPDFium2Loader`, has a
  permissive licence (pypdfium2 Apache-2.0/BSD-3-Clause; PDFium BSD-style [20]), and adds **no new
  dependency**. It did read differently in the local runs: it expands ligatures (`'Office efficient'` where
  the others give U+FB00 + `i`), marks line-end hyphens as U+FFFE (`'in\ufffecluded'`), uses `\r\n`, and
  splits letterspaced small caps differently (`'Sen ior So ftware Eng ineer'`). The adapter must map U+FFFE
  to a soft hyphen (or remove it with the newline) and `\r\n` to `\n`, otherwise `check._is_junk` treats
  U+FFFE (category Cn) as junk.
- **Also add a `pdfminer` (high-level) adapter**, for the reason in finding 1. This is the call Resume
  Matcher, pyresparser and Unstructured actually make.
- **pdf.js**: independent and used by OpenResume (Apache-2.0 [17]), but needs Node and `pdfjs-dist` at
  check time. Worth it only if a browser-side screener is a target; keep as a later optional adapter.
- **PDFBox/Tika**: independent and widely deployed in enterprise ATS pipelines (Apache-2.0 [13]) but needs a
  JVM and either a Tika server or a jar; too heavy for the default install. Optional at most.
- **PyMuPDF/MuPDF**: independent, but AGPL-3.0 or commercial [16]; importing it would make AGPL terms apply
  to anyone who distributes cvforge with it. Do not add; if ever wanted, shell out to a user-installed
  `mutool draw -F txt` instead of importing.

## Question B: LaTeX settings that break extraction

"Local" quotes the reproduction; extractor names: pop = pdftotext raw, popL = `-layout`, plb = pdfplumber,
pdfm = pdfminer high-level, pyp = pypdf default, pdfium = pypdfium2.

| Setting | Mechanism | Symptom in extracted text (local) | Mitigation | Source |
|---|---|---|---|---|
| `\usepackage[T1]{fontenc}` under pdflatex with no Type 1 T1 font (cm-super missing, no `lmodern`) | pdfTeX falls back to Metafont bitmaps: **Type 3** fonts with no ToUnicode map (`pdffonts`: `Type 3 ... uni no`) | Ligatures lost in **all** extractors: `'O\x1ece e\x1ecient \x1duent work\x1dow'` (plb: `'O(cid:30)ce'`, `'rØsumØ'`); pyp `'Softw are'` | Add `\usepackage{lmodern}` (or another Type 1 font package) after fontenc, or install cm-super | [26][27] *(snippet)*; local |
| Default **OT1** encoding under pdflatex (no `\usepackage[T1]{fontenc}`) | OT1 has no accented glyphs; TeX overlays a separate accent glyph on the base letter | Accented names split: plb `'Mu¨ller r´esum´e'`, pyp `'M¨ uller r´ esum´ e'`, pdfium `'M¨uller'`; poppler recombines. NFKC in `check.normalize` does not repair this | `\usepackage[T1]{fontenc}` + `\usepackage{lmodern}` | [28] *(snippet)*; local |
| fontspec (XeLaTeX) common ligatures | Font substitutes one glyph for fi/ffi/ff; ToUnicode maps it to a presentation-form code point | `'Oﬀice eﬀicient'` (U+FB00) in pop, plb, pyp; pdfium expands. NFKC in `check.normalize` repairs these; fonts whose ligature glyph has no mapping still lose it. LuaLaTeX output was clean | `Ligatures=CommonOff` (alias `NoCommon`); **must take effect before the main font is loaded**: `\defaultfontfeatures{...}` after `\usepackage{fontspec}` with no later `\setmainfont` left ligatures on locally; `\setmainfont{...}[Ligatures=CommonOff]` worked | [24]; [25] *(snippet)*; fontspec-xetex.sty `\__fontspec_ot_compat:nn` aliases `NoCommon` to `CommonOff`; local |
| Missing `\input{glyphtounicode}` + `\pdfgentounicode=1` (or `cmap` package) under pdflatex | pdfTeX writes ToUnicode only for glyph names it can map; fonts with non-standard glyph names (symbols, some expert/small-caps sets) need the table | No difference observed with lmodern, libertine, charter, helvet, mathpazo, fourier, kpfonts, ebgaramond, fontawesome; the risk is font-specific | Keep both lines in pdflatex templates (minimal.tex and jakes-resume already do) | [29] *(snippet)*; local |
| microtype tracking (`tracking=true`, `\textls`, `\lsstyle`) | Letterspacing is done by kerns between glyphs, so gaps inside words approach the extractor's word gap | pop/popL/pyp/pdfm `'S e n i o r S o f t wa r e E n g i n e e r'` (default tracking set = small caps); pdfium `'Sen ior So ftware'`; plb fine | Do not letterspace text; `tracking=false` (the default) | [22] (microtype.dtx, letterspacing section); [30] *(snippet)*; local |
| Icon fonts (fontawesome, fontawesome5, marvosym, academicons) | Icon glyphs map to private-use or arbitrary code points | pop/plb/pdfium `'# alex@example.org § alexdev \x83 0400...'` (plb `(cid:131)`); pyp `'✉ ... /githubalexdev ♂phone0400'` (glyph names glued to text) | Words instead of icons; or wrap icons in `accsupp` `ActualText` (altacv does this) | [31][32] *(snippet)*; local. Already linted |
| `\textsc` / `\scshape` with fonts lacking true small caps (helvet, charter, mathpazo, fourier) | Small caps faked from capitals in two sizes | pop/popL `'S ENIOR S OFTWARE E NGINEER'`; plb `'SENIORSOFTWAREENGINEER'` (mathpazo, fourier); others `'SENIOR SOFTWARE ENGINEER'` (case changed). True small caps (lmodern, libertine, kpfonts, OpenType `+smcp`) extract as the typed lowercase | Avoid `\textsc` for searchable fields (name, titles), or use a font with real small caps | [24] (small caps keep the underlying text); local |
| Tight interword spacing (`\spaceskip`, condensed fonts, aggressive microtype expansion in narrow boxes) | PDF has no space characters from TeX; extractors infer spaces from gaps | `'JoinedAcmeWidgetsinSydneyaslead'` (plb, pyp, pdfium); pop fine. `\pdfinterwordspaceon` did **not** fix it for plb/pyp/pdfium here | Keep default spacing; `\pdfinterwordspaceon` (pdfTeX only) adds fake space glyphs but drops them at font switches and overfull lines | [22][23]; [33][34][35] *(snippet)*; local |
| Hyphenation | TeX breaks words with a visible hyphen; no soft-hyphen marker is written | popL/plb/pyp/pdfm `'in-\ncluded internation-\nalisation'`; pdfium `'in\ufffecluded'`; pop raw joins. `check.extracted_variants` already joins `-\n` | `\hyphenpenalty=10000 \exhyphenpenalty=10000` or `\usepackage[none]{hyphenat}`, plus `\raggedright` | [36] *(snippet)*; local |
| `tabular` / `p{}` columns, `multicol`, `paracol` | Cells are absolutely positioned text; extractors read across rows | pop raw `'Skills: Python, Go, Rust Languages:\nEnglish,\nand more\nFrench and German'` (cells interleaved); plb joins row halves; pyp/pdfium read cell by cell | Single column; one fact per line; `tabular*` only for a title/date pair | [22] ("tables are just absolutely positioned text"); local. Two-column already linted |

### Candidate lint additions

Ordered by evidence strength. The corpus column says which corpus template would trigger the rule
(`tests/fixtures/templates/`), so the main agent can apply its "only where a corpus template demonstrates
the breakage" test.

1. **OT1 under pdflatex**: no `\usepackage[T1]{fontenc}` (and no fontspec). Fires on **jakes-resume**
   (OT1; accented names split in plb, pyp, pdfium). Sources: [28], local. Fix: add `\usepackage[T1]{fontenc}`
   and `\usepackage{lmodern}`.
2. **T1 without a Type 1 font**: `fontenc` with `T1` and no font package (`lmodern`, `libertine`, `charter`,
   `mathpazo`, `helvet`, `tgheros` ...). Produces Type 3 fonts wherever cm-super is absent; every extractor
   loses ligatures. No corpus template triggers it today (minimal.tex and altacv load lmodern / cmap); keep
   as a candidate. Sources: [26][27], local.
3. **Fix the existing fontspec rule** (not a new rule): accept `Ligatures=CommonOff` as well as `NoCommon`
   (fontspec aliases them), and change the fix text: `\defaultfontfeatures` only applies to fonts loaded
   after it, so it must precede `\setmainfont`, or the option goes on `\setmainfont[...]`. Fires on
   **awesome-cv** (`Ligatures=TeX` only), **deedy-resume**, **moderncv** (fontspec branch). Sources: [24],
   fontspec-xetex.sty, local.
4. **microtype letterspacing**: `\textls`, `\lsstyle`, `\SetTracking`, or `microtype` with `tracking=`
   other than `false`. No corpus template triggers it. Sources: [22][30], local.
5. **`\textsc`/`\scshape` on a placeholder line** (name, job title) when the font has no true small caps.
   Fires on **jakes-resume** (`\scshape` name and section titles, but with CM's real small caps it extracted
   cleanly locally) and **awesome-cv** / **deedy-resume** (`\scshape` with fontspec fonts). Needs a corpus
   check before adding; the breakage depends on the font. Sources: [24], local.
6. **Hyphenation left on**: no `\hyphenpenalty=10000` / `hyphenat[none]`. Advisory only, since `check`
   already joins `-\n`; worth a lint only if a pdfium adapter is added (U+FFFE). Sources: [36], local.

Not recommended as lint rules: `glyphtounicode`/`cmap` absence (no breakage reproduced with common fonts;
`check` will catch font-specific cases) and `\pdfinterwordspaceon` (did not help the extractors that failed).

## Sources

Fetched (raw files):

1. https://raw.githubusercontent.com/opencats/OpenCATS/master/lib/DocumentToText.php
2. https://raw.githubusercontent.com/srbhr/Resume-Matcher/main/apps/backend/pyproject.toml
3. https://raw.githubusercontent.com/srbhr/Resume-Matcher/main/apps/backend/requirements.txt
4. https://raw.githubusercontent.com/srbhr/Resume-Matcher/main/apps/backend/app/services/parser.py
5. https://raw.githubusercontent.com/microsoft/markitdown/main/packages/markitdown/src/markitdown/converters/_pdf_converter.py
6. https://raw.githubusercontent.com/microsoft/markitdown/main/packages/markitdown/pyproject.toml
7. https://raw.githubusercontent.com/xitanggg/open-resume/main/package.json
8. https://raw.githubusercontent.com/xitanggg/open-resume/main/src/app/lib/parse-resume-from-pdf/read-pdf.ts
9. https://raw.githubusercontent.com/OmkarPathak/pyresparser/master/requirements.txt
10. https://raw.githubusercontent.com/OmkarPathak/pyresparser/master/pyresparser/utils.py
11. https://raw.githubusercontent.com/langchain-ai/langchain-community/main/libs/community/langchain_community/document_loaders/parsers/pdf.py
12. https://raw.githubusercontent.com/run-llama/llama_index/main/llama-index-integrations/readers/llama-index-readers-file/llama_index/readers/file/docs/base.py
13. https://raw.githubusercontent.com/apache/tika/main/tika-parsers/tika-parsers-standard/tika-parsers-standard-modules/tika-parser-pdf-module/pom.xml
14. https://raw.githubusercontent.com/Unstructured-IO/unstructured/main/pyproject.toml
15. https://raw.githubusercontent.com/docling-project/docling/main/pyproject.toml
16. https://raw.githubusercontent.com/pymupdf/PyMuPDF/main/README.md
17. https://raw.githubusercontent.com/mozilla/pdf.js/master/LICENSE
18. https://raw.githubusercontent.com/py-pdf/pypdf/main/LICENSE
19. https://raw.githubusercontent.com/pdfminer/pdfminer.six/master/LICENSE
20. https://raw.githubusercontent.com/pypdfium2-team/pypdfium2/main/README.md
21. https://raw.githubusercontent.com/jsvine/pdfplumber/stable/requirements.txt
22. https://raw.githubusercontent.com/py-pdf/pypdf/main/docs/user/extract-text.md and
    https://raw.githubusercontent.com/schlcht/microtype/master/microtype.dtx
23. https://raw.githubusercontent.com/pdfminer/pdfminer.six/master/docs/source/topic/converting_pdf_to_text.rst
24. https://raw.githubusercontent.com/latex3/fontspec/main/fontspec-doc-opentype.tex (also
    https://raw.githubusercontent.com/latex3/fontspec/main/README.md; local
    `/usr/share/texlive/texmf-dist/tex/latex/fontspec/fontspec-xetex.sty` lines 3133-3139)

Search results only (host blocked for fetching; used for the snippet quoted):

25. https://tug.org/pipermail/xetex/2010-June/016880.html (XeTeX ligatures and searching)
26. https://latex.org/forum/viewtopic.php?p=66326 (Type 3 vs Type 1, cm-super)
27. https://archive.lists.launchpad.net/registry/msg25954.html (LyX bug: T1 bitmap fonts, lmodern)
28. https://www.overleaf.com/learn/latex/German (OT1 constructed accents copy as two characters)
29. https://tug.org/pipermail/tex-live/2009-February/019970.html (ligature copy, glyphtounicode, `\pdfgentounicode`)
30. https://texfaq.org/FAQ-letterspace (letterspacing via microtype)
31. https://atsverification.com/blog/latex-resume-ats-friendly/ (icon fonts and ATS parsing)
32. https://www.tug.org/pipermail/texhax/2010-December/016284.html (`\pdfglyphtounicode`, accsupp ActualText)
33. https://tug.org/pipermail/pdftex/2019-December/009167.html (`\pdfinterwordspaceon`)
34. https://tug.org/pipermail/pdftex/2024-July/009424.html (space chars missing at font switches)
35. https://tug.org/pipermail/pdftex/2024-April/009388.html (space chars lost in overfull lines)
36. https://texfaq.org/FAQ-hyphoff (stopping hyphenation)

## What was implemented

Per work order 2 item 7, lint additions were made only where a corpus template shows the breakage
(see `docs/parser-table.md` and `DECISIONS.md`): the OT1-encoding rule (candidate 1, shown by
Jake's Resume losing underscores) and the fontspec rule fix (candidate 3). Candidates 2, 4, 5 and
6 are not implemented because no corpus template demonstrates them. No adapter was added: the
PDFium and pdfminer high-level adapters are recommendations awaiting a decision.
