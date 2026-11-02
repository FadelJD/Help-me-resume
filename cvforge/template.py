"""Template contract: declare, validate, render with Jinja2 using LaTeX-safe delimiters.

With `cvforge/escape.py`, this is the only module that knows LaTeX syntax for rendering.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from difflib import get_close_matches
from pathlib import Path
from typing import Any

import jinja2
from jinja2 import nodes

from cvforge.config import Locale
from cvforge.errors import CVForgeError, Issue
from cvforge.escape import escape, escape_url
from cvforge.schema import Education, Experience, Hat, Profile, Project, SelectedItem, Selection

HEADER_MAGIC = "%% cvforge-template v1"
HEADER_KEYS = ("sections", "supports", "max-bullets-per-role", "max-pages", "engine")
ENGINE_NAMES = ("pdflatex", "xelatex", "lualatex")
SECTIONS = ("experience", "projects", "skills", "education")

# Optional fields a template must declare under `%% supports:` before using them.
FEATURES: dict[str, str] = {
    "person.links": "person.links",
    "person.links.text": "person.links",
    "person.links.href": "person.links",
    "person.phone": "person.phone",
    "experience.location": "experience.location",
    "experience.bullets.skills": "bullet.skills",
    "projects.bullets.skills": "bullet.skills",
    "education.bullets.skills": "bullet.skills",
    "projects.url": "projects.url",
    "projects.href": "projects.url",
    "projects.stack": "projects.stack",
    "education.location": "education.location",
    "skill_groups": "skills.groups",
    "skill_groups.name": "skills.groups",
    "skill_groups.skills": "skills.groups",
}
FEATURE_NAMES = sorted(set(FEATURES.values()))

_BULLET = ("bullets", "bullets.id", "bullets.text", "bullets.skills")
_DATES = ("start", "end", "start_raw", "end_raw")
ALLOWED: set[str] = {
    "person",
    "person.name",
    "person.email",
    "person.location",
    "person.title_line",
    "meta",
    *(
        f"meta.{k}"
        for k in (
            "hat",
            "job_title",
            "build_date",
            "version",
            "locale",
            "cv_word",
            "paper",
            "sections",
        )
    ),
    "experience",
    *(f"experience.{k}" for k in ("id", "title", "org", *_DATES, *_BULLET)),
    "projects",
    *(f"projects.{k}" for k in ("id", "name", *_DATES, *_BULLET)),
    "education",
    *(f"education.{k}" for k in ("id", "degree", "org", *_DATES, *_BULLET)),
    "skills",
    *FEATURES,
}
ROOTS = {p.split(".")[0] for p in ALLOWED}
SECTION_OF_ROOT = {"experience": "experience", "projects": "projects", "education": "education"}
SECTION_OF_ROOT.update({"skills": "skills", "skill_groups": "skills"})
JINJA_GLOBALS = {
    "range",
    "dict",
    "lipsum",
    "cycler",
    "joiner",
    "namespace",
    "loop",
    "true",
    "false",
}


@dataclass(frozen=True)
class Header:
    sections: tuple[str, ...]
    supports: tuple[str, ...]
    max_bullets: int | None
    max_pages: int | None
    engine: str = "pdflatex"


@dataclass(frozen=True)
class Use:
    path: str
    line: int


@dataclass
class TemplateReport:
    file: str
    header: Header | None
    issues: list[Issue] = field(default_factory=list)
    lint: list[Issue] = field(default_factory=list)
    will_fill: list[str] = field(default_factory=list)
    empty: list[str] = field(default_factory=list)
    left_out: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)  # placeholder paths the template uses
    fixed_text: list[tuple[int, str]] = field(default_factory=list)  # (line, visible text)

    @property
    def ok(self) -> bool:
        return self.header is not None and not [i for i in self.issues if i.severity == "error"]

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "file": self.file,
            "sections": list(self.header.sections) if self.header else [],
            "supports": list(self.header.supports) if self.header else [],
            "max_bullets_per_role": self.header.max_bullets if self.header else None,
            "will_fill": self.will_fill,
            "empty": self.empty,
            "left_out": self.left_out,
            "filled_fields": self.fields,
            "fixed_text": [{"line": line, "text": text} for line, text in self.fixed_text],
            "issues": [i.to_dict() for i in self.issues],
            "lint": [i.to_dict() for i in self.lint],
        }


def environment() -> jinja2.Environment:
    return jinja2.Environment(
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        variable_start_string=r"\VAR{",
        variable_end_string="}",
        comment_start_string=r"\#{",
        comment_end_string="}",
        line_statement_prefix=None,
        line_comment_prefix=None,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )


# ---------------------------------------------------------------- header


def parse_header(text: str, file: str) -> tuple[Header | None, list[Issue]]:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip()), 0)
    if not lines or lines[start].strip() != HEADER_MAGIC:
        return None, [
            Issue(
                file=file,
                line=start + 1,
                message=f"missing the `{HEADER_MAGIC}` header block.",
                fix="add the header block from templates/minimal.tex as the first lines.",
            )
        ]
    issues: list[Issue] = []
    values: dict[str, tuple[str, int]] = {}
    for idx in range(start + 1, len(lines)):
        line = lines[idx].strip()
        if not line.startswith("%%"):
            break
        body = line[2:].strip()
        if not body:
            continue
        key, sep, value = body.partition(":")
        key = key.strip()
        if not sep or key not in HEADER_KEYS:
            issues.append(
                Issue(
                    file=file,
                    line=idx + 1,
                    message=f"unknown header line `{line}`.",
                    fix=f"use one of: {', '.join(k + ':' for k in HEADER_KEYS)}.",
                )
            )
            continue
        values[key] = (value.strip(), idx + 1)

    def _list(key: str, allowed: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        raw, line = values.get(key, ("", start + 1))
        items = tuple(x.strip() for x in raw.split(",") if x.strip())
        for x in items:
            if x not in allowed:
                hint = get_close_matches(x, list(allowed), n=1)
                issues.append(
                    Issue(
                        file=file,
                        line=line,
                        message=f"`{key}` lists unknown value `{x}`.",
                        fix=f"use one of: {', '.join(allowed)}."
                        + (f" Did you mean `{hint[0]}`?" if hint else ""),
                    )
                )
        return tuple(x for x in items if x in allowed)

    def _int(key: str) -> int | None:
        if key not in values:
            return None
        raw, line = values[key]
        if not raw.isdigit() or int(raw) < 1:
            issues.append(
                Issue(
                    file=file,
                    line=line,
                    message=f"`{key}` must be a whole number of 1 or more.",
                    fix=f"write e.g. `%% {key}: 5`.",
                )
            )
            return None
        return int(raw)

    sections = _list("sections", SECTIONS)
    if "sections" not in values:
        issues.append(
            Issue(
                file=file,
                line=start + 2,
                message="header has no `sections:` line.",
                fix="add e.g. `%% sections: experience, projects, skills, education`.",
            )
        )
    engine_list = _list("engine", ENGINE_NAMES) if "engine" in values else ("pdflatex",)
    header = Header(
        sections=sections,
        supports=_list("supports", FEATURE_NAMES),
        max_bullets=_int("max-bullets-per-role"),
        max_pages=_int("max-pages"),
        engine=engine_list[0] if engine_list else "pdflatex",
    )
    return header, issues


# ---------------------------------------------------------------- placeholder analysis


class _Analyzer:
    def __init__(self) -> None:
        self.uses: list[Use] = []

    def resolve(self, node: nodes.Node, scope: dict[str, str | None]) -> str | None:
        if isinstance(node, nodes.Name):
            if node.name in scope:
                return scope[node.name]
            if node.name in JINJA_GLOBALS:
                return None
            return node.name
        if isinstance(node, nodes.Getattr):
            base = self.resolve(node.node, scope)
            return None if base is None else f"{base}.{node.attr}"
        if isinstance(node, nodes.Getitem):
            base = self.resolve(node.node, scope)
            arg = node.arg
            if isinstance(arg, nodes.Const) and isinstance(arg.value, str):
                return None if base is None else f"{base}.{arg.value}"
            self.visit(arg, scope)
            return base
        self.visit(node, scope)
        return None

    def record(self, node: nodes.Node, scope: dict[str, str | None]) -> None:
        path = self.resolve(node, scope)
        if path is not None:
            self.uses.append(Use(path, node.lineno))

    def visit(self, node: nodes.Node, scope: dict[str, str | None]) -> None:
        if isinstance(node, nodes.Name | nodes.Getattr | nodes.Getitem):
            self.record(node, scope)
            return
        if isinstance(node, nodes.For):
            self.visit(node.iter, scope)
            inner = dict(scope)
            iter_path = self.resolve(node.iter, {**scope}) if _is_ref(node.iter) else None
            for name in _target_names(node.target):
                inner[name] = iter_path if isinstance(node.target, nodes.Name) else None
            if node.test is not None:
                self.visit(node.test, inner)
            for child in node.body:
                self.visit(child, inner)
            for child in node.else_:
                self.visit(child, scope)
            return
        if isinstance(node, nodes.Assign):
            self.visit(node.node, scope)
            for name in _target_names(node.target):
                scope[name] = self.resolve(node.node, scope) if _is_ref(node.node) else None
            return
        if isinstance(node, nodes.Macro | nodes.CallBlock):
            inner = dict(scope)
            for arg in getattr(node, "args", []):
                inner[arg.name] = None
            for name in ("varargs", "kwargs", "caller"):
                inner[name] = None
            for child in node.body:
                self.visit(child, inner)
            if isinstance(node, nodes.CallBlock):
                self.visit(node.call, scope)
            return
        if isinstance(node, nodes.Call) and isinstance(node.node, nodes.Getattr):
            self.record(node.node.node, scope)  # x.items(): the object is the placeholder
            for child in [*node.args, *node.kwargs]:
                self.visit(child, scope)
            return
        for child in node.iter_child_nodes():
            self.visit(child, scope)


def _is_ref(node: nodes.Node) -> bool:
    return isinstance(node, nodes.Name | nodes.Getattr | nodes.Getitem)


def _target_names(target: nodes.Node) -> Iterator[str]:
    if isinstance(target, nodes.Name):
        yield target.name
    elif isinstance(target, nodes.Tuple):
        for item in target.items:
            yield from _target_names(item)


def analyze(text: str, file: str) -> tuple[list[Use], list[Issue]]:
    try:
        ast = environment().parse(text)
    except jinja2.TemplateSyntaxError as exc:
        return [], [
            Issue(
                file=file,
                line=exc.lineno,
                message=f"template syntax error: {exc.message}.",
                fix="close every \\BLOCK{for} and \\BLOCK{if} with \\BLOCK{endfor}/\\BLOCK{endif}.",
            )
        ]
    analyzer = _Analyzer()
    scope: dict[str, str | None] = {m.name: None for m in ast.find_all(nodes.Macro)}
    analyzer.visit(ast, scope)
    return analyzer.uses, []


# ---------------------------------------------------------------- fixed text

# Commands whose arguments are never printed: drop the command and all its brace/bracket groups.
_INVISIBLE = {
    "begin",
    "end",
    "vspace",
    "hspace",
    "vskip",
    "hskip",
    "setlength",
    "addtolength",
    "label",
    "ref",
    "includegraphics",
    "input",
    "include",
    "pagestyle",
    "thispagestyle",
    "newcommand",
    "renewcommand",
    "setlist",
    "rule",
    "fontsize",
    "linespread",
    "definecolor",
    "usepackage",
    "color",
    "titleformat",
    "titlespacing",
    "geometry",
    "setcounter",
    "addtocounter",
    "phantom",
    "extracolsep",
    "arraystretch",
    "pdfgentounicode",
    "selectfont",
    "fontspec",
    "newpage",
}
# Commands whose first argument is invisible and the rest printed.
_FIRST_INVISIBLE = {"href", "textcolor", "colorbox", "raisebox", "parbox", "makebox"}


def _skip_group(text: str, i: int) -> int:
    """Index after a balanced {...} or [...] group starting at text[i]."""
    open_ch = text[i]
    close_ch = "}" if open_ch == "{" else "]"
    depth = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return i


def visible_text(code: str) -> str:
    """Rough plain text a LaTeX fragment prints. Used to list fixed text, not to typeset."""
    out: list[str] = []
    i = 0
    while i < len(code):
        ch = code[i]
        if ch == "\\":
            m = re.match(r"\\([A-Za-z@]+\*?|.)", code[i:])
            assert m is not None
            name = m.group(1).rstrip("*")
            i += len(m.group(0))
            if len(name) == 1 and not name.isalpha():
                out.append(name if name in "&%$#_{}" else " ")
                continue
            while i < len(code) and code[i] == " ":
                i += 1
            if name in _INVISIBLE:
                while i < len(code) and code[i] in "{[":
                    i = _skip_group(code, i)
            elif name in _FIRST_INVISIBLE:
                while i < len(code) and code[i] == "[":
                    i = _skip_group(code, i)
                if i < len(code) and code[i] == "{":
                    i = _skip_group(code, i)
            else:
                while i < len(code) and code[i] == "[":
                    i = _skip_group(code, i)
                out.append(" ")
            continue
        out.append(" " if ch in "{}&~^$" else ch)
        i += 1
    return " ".join("".join(out).split())


def fixed_text(text: str) -> list[tuple[int, str]]:
    """Visible text in the document body that is not inside \\VAR{}, \\BLOCK{} or \\#{}.

    Anything outside those tags is fixed by definition: it is printed exactly as written.
    """
    try:
        ast = environment().parse(text)
    except jinja2.TemplateSyntaxError:
        return []
    lines = text.splitlines()
    begin = next((i for i, row in enumerate(lines) if "\\begin{document}" in _code(row)), None)
    end = next((i for i, row in enumerate(lines) if "\\end{document}" in _code(row)), len(lines))
    if begin is None:
        return []
    found: list[tuple[int, str]] = []
    for node in ast.find_all(nodes.TemplateData):
        for offset, row in enumerate(node.data.split("\n")):
            line_no = node.lineno + offset
            if not begin + 1 < line_no <= end:
                continue
            words = visible_text(_code(row))
            if any(c.isalpha() for c in words):
                found.append((line_no, words))
    return found


_PERSONAL = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.]+|https?://|www\.|(?:github|linkedin)\.com|\+?\d[\d ()-]{7,}\d|"
    r"\b(19|20)\d{2}\b"
)


def personal_fact_warnings(fixed: list[tuple[int, str]], file: str) -> list[Issue]:
    issues = []
    for line, text in fixed:
        if _PERSONAL.search(text):
            issues.append(
                Issue(
                    file=file,
                    line=line,
                    severity="warning",
                    message=f"fixed text looks like a personal fact: {text!r}.",
                    fix="facts about you belong in profile.cv.txt; replace it with a \\VAR{} "
                    "placeholder unless it is meant to be constant.",
                )
            )
    return issues


# ---------------------------------------------------------------- lint


_TWO_COLUMN = re.compile(
    r"\\usepackage(\[[^\]]*\])?\{[^}]*\b(multicol|paracol)\b|\\begin\{(multicols|paracol)\}"
    r"|\\twocolumn\b"
)
# Side-by-side minipages narrower than the page (Deedy Resume in the corpus).
_NARROW_MINIPAGE = re.compile(r"\\begin\{minipage\}(\[[^\]]*\])?\{0?\.[0-7]\d*\\(text|line)width\}")
_ICON_PACKAGE = re.compile(
    r"\\usepackage(\[[^\]]*\])?\{[^}]*\b(fontawesome[5-7]?|academicons|marvosym|simpleicons)\b"
)
# Icon commands actually used: Font Awesome (\faX, \faIcon) and common marvosym symbols.
_ICON_USE = re.compile(
    r"\\fa[A-Z]\w*|\\faIcon\b|\\(Letter|Email|EmailCT|Mobilefone|Telefon|Mundus|Pointinghand|"
    r"Clocklogo|Industry|Faxmachine|Lightning|Mobilefone|Writinghand|Gentsroom)\b|\\ai[A-Z]\w*"
)
# Header or footer commands with something visible in their argument (Jake's empty
# \fancyfoot{} is harmless and no longer warns).
_HEADER_TEXT = re.compile(
    r"\\(fancyhead|fancyfoot|lhead|chead|rhead|lfoot|cfoot|rfoot)(\[[^\]]*\])?\{\s*[^}\s]"
)
_STANDARD_CLASS = re.compile(
    r"\\documentclass(\[[^\]]*\])?\{(article|extarticle|report|extreport|scrartcl|memoir|letter)\}"
)
_RIGHT_ALIGN = re.compile(
    r"\\hfill\b|\\extracolsep\{\\fill\}|\\hspace\*\{\\fill\}|\\raggedleft\b|"
    r"\\begin\{flushright\}|\\rightline\b|\\hfil\b"
)
_DATE_PLACEHOLDER = re.compile(r"\\VAR\{[^}]*\.(start|end)(_raw)?\b")


def _code(line: str) -> str:
    """The part of a line before an unescaped % comment."""
    return re.split(r"(?<!\\)%", line, maxsplit=1)[0]


def _first_line(lines: list[str], pattern: re.Pattern[str]) -> int | None:
    return next((i + 1 for i, row in enumerate(lines) if pattern.search(_code(row))), None)


def lint(text: str, file: str, engine: str | None = None) -> list[Issue]:
    """Parser-safety warnings. Each rule is backed by a corpus template that shows the damage
    (docs/parser-table.md) or by a known extraction failure (docs/research.md)."""
    found: list[Issue] = []
    lines = text.splitlines()
    code = "\n".join(_code(row) for row in lines)

    def warn(line: int | None, message: str, fix: str) -> None:
        found.append(Issue(file=file, line=line, severity="warning", message=message, fix=fix))

    if engine is None:
        header, _ = parse_header(text, file)
        engine = header.engine if header else "pdflatex"

    if _DATE_PLACEHOLDER.search(code):
        for idx, line in enumerate(lines):
            row = _code(line).strip()
            if row == "\\hfill":  # a gap between side-by-side boxes, not aligned dates
                continue
            if _RIGHT_ALIGN.search(row):
                warn(
                    idx + 1,
                    "right-aligned dates may separate from titles in some parsers "
                    "(\\hfill, \\extracolsep{\\fill} or similar).",
                    "usually harmless, because check tests each field on its own; put dates "
                    "inline if a parser you rely on reorders them.",
                )
                break
    two_col = _first_line(lines, _TWO_COLUMN)
    if two_col is None and len(_NARROW_MINIPAGE.findall(code)) >= 2:
        two_col = _first_line(lines, _NARROW_MINIPAGE)
    if two_col is not None:
        warn(
            two_col,
            "two-column layout: parsers often read across columns and interleave lines.",
            "use a single column in reading order; keep dates on the line they belong to.",
        )
    if _ICON_PACKAGE.search(code) and _ICON_USE.search(code.split("\\begin{document}")[-1]):
        warn(
            _first_line(lines, _ICON_PACKAGE),
            "icon font: icons extract as junk characters or vanish, taking adjacent text with "
            "them.",
            "write the words (Email, GitHub) instead of icons.",
        )
    if "\\includegraphics" in code:
        warn(
            _first_line(lines, re.compile(r"\\includegraphics")),
            "\\includegraphics (photo or logo): invisible to parsers and a bias risk in screening.",
            "remove the image; keep information as text.",
        )
    if _HEADER_TEXT.search(code):
        warn(
            _first_line(lines, _HEADER_TEXT),
            "text in headers/footers: many parsers drop it or repeat it on every page.",
            "move contact details into the body.",
        )
    if engine == "pdflatex" and _STANDARD_CLASS.search(code) and "fontenc" not in code:
        warn(
            _first_line(lines, _STANDARD_CLASS),
            "pdfLaTeX with the default OT1 font encoding: underscores are drawn as rules and "
            "accents as separate marks, so 'my_project' extracts as 'my project'.",
            "add \\usepackage[T1]{fontenc} (with \\usepackage{lmodern} or another Type 1 font).",
        )
    if "fontspec" in code and not re.search(r"Ligatures\s*=\s*\{?\s*(NoCommon|CommonOff)", code):
        warn(
            _first_line(lines, re.compile("fontspec")),
            "fontspec without Ligatures=NoCommon: ligatures like 'fi' can extract as one "
            "unknown glyph.",
            "add Ligatures=NoCommon to the font options, or \\defaultfontfeatures{Ligatures="
            "NoCommon} before the first \\setmainfont.",
        )
    return found


# ---------------------------------------------------------------- validate


def validate_template(
    path: Path, profile_sections: list[str] | None = None
) -> tuple[str, TemplateReport]:
    file = str(path)
    if not path.exists():
        raise CVForgeError(
            [
                Issue(
                    file=file,
                    item="--template",
                    message="template not found.",
                    fix="pass --template, or set template = in cvforge.toml.",
                )
            ]
        )
    text = path.read_text(encoding="utf-8")
    header, issues = parse_header(text, file)
    report = TemplateReport(file=file, header=header, issues=issues, lint=lint(text, file))
    if header is None:
        return text, report
    uses, syntax = analyze(text, file)
    report.issues.extend(syntax)
    if syntax:
        return text, report
    report.fields = sorted({u.path for u in uses if u.path in ALLOWED})
    report.fixed_text = fixed_text(text)
    report.issues.extend(personal_fact_warnings(report.fixed_text, file))
    text_lines = text.splitlines()
    used_roots: set[str] = set()
    used_features: set[str] = set()
    for use in uses:
        root = use.path.split(".")[0]
        if root not in ROOTS:
            hint = get_close_matches(root, sorted(ROOTS), n=1)
            report.issues.append(
                Issue(
                    file=file,
                    line=use.line,
                    message=f"unknown placeholder `{use.path}`.",
                    fix=f"use one of: {', '.join(sorted(ROOTS))}."
                    + (f" Did you mean `{hint[0]}`?" if hint else ""),
                )
            )
            continue
        if use.path not in ALLOWED:
            hint = get_close_matches(use.path, sorted(ALLOWED), n=1)
            report.issues.append(
                Issue(
                    file=file,
                    line=use.line,
                    message=f"unknown field `{use.path}`.",
                    fix="see 'Available context' in docs/SPEC.md."
                    + (f" Did you mean `{hint[0]}`?" if hint else ""),
                )
            )
            continue
        used_roots.add(root)
        section = SECTION_OF_ROOT.get(root)
        if section and section not in header.sections:
            report.issues.append(
                Issue(
                    file=file,
                    line=use.line,
                    message=f"`{use.path}` is used but `{section}` is not in `%% sections:`.",
                    fix=f"add {section} to the sections: header line.",
                )
            )
        feature = FEATURES.get(use.path)
        if feature:
            used_features.add(feature)
            if feature not in header.supports:
                report.issues.append(
                    Issue(
                        file=file,
                        line=use.line,
                        message=f"`{use.path}` is used but `{feature}` is not in `%% supports:`.",
                        fix=f"add {feature} to the supports: header line.",
                    )
                )
        if use.path.endswith("bullets.text"):
            id_path = use.path[: -len("text")] + "id"
            line_text = text_lines[use.line - 1] if use.line - 1 < len(text_lines) else ""
            has_id = any(u.line == use.line and u.path == id_path for u in uses)
            if not has_id or "% id:" not in line_text:
                report.issues.append(
                    Issue(
                        file=file,
                        line=use.line,
                        message="bullet text is emitted without its `% id:` comment.",
                        fix="end the line with `% id:\\VAR{b.id}` (b = your loop variable).",
                    )
                )
    for section in header.sections:
        roots = [r for r, s in SECTION_OF_ROOT.items() if s == section]
        if not used_roots.intersection(roots):
            report.issues.append(
                Issue(
                    file=file,
                    severity="warning",
                    message=f"`{section}` is declared in `%% sections:` but never used.",
                    fix=f"render it with \\BLOCK{{for x in {section}}} or drop it from the header.",
                )
            )
    for feature in header.supports:
        if feature not in used_features:
            report.issues.append(
                Issue(
                    file=file,
                    severity="warning",
                    message=f"`{feature}` is declared in `%% supports:` but never used.",
                    fix="use it in the template or remove it from the header.",
                )
            )
    if profile_sections is not None:
        report.will_fill = [s for s in header.sections if s in profile_sections]
        report.empty = [s for s in header.sections if s not in profile_sections]
        report.left_out = [s for s in profile_sections if s not in header.sections]
    return text, report


# ---------------------------------------------------------------- render


def render(text: str, context: dict[str, Any], file: str) -> str:
    try:
        return environment().from_string(text).render(**context)
    except jinja2.TemplateSyntaxError as exc:
        raise CVForgeError(
            [
                Issue(
                    file=file,
                    line=exc.lineno,
                    message=f"template syntax error: {exc.message}.",
                    fix="run `cvforge template validate` for details.",
                )
            ]
        ) from exc
    except jinja2.UndefinedError as exc:
        raise CVForgeError(
            [
                Issue(
                    file=file,
                    message=f"template uses an undefined value: {exc.message}.",
                    fix="run `cvforge template validate` to find the placeholder.",
                )
            ]
        ) from exc


def check_traceability(
    tex: str, emitted: dict[str, str], file: str
) -> tuple[set[str], list[Issue]]:
    """Every emitted bullet must sit on a line carrying its own `% id:` comment.

    `emitted` maps qualified bullet id -> escaped text; `file` is the output .tex. A bullet counts
    as found on the line whose id comment names it. It is an error when a bullet's id appears on
    no line but its text does: that text was emitted without its id. Text that merely repeats
    elsewhere (the same wording in two roles, a short bullet inside another) is not an error.
    Returns the ids found in the output.
    """
    issues: list[Issue] = []
    found: set[str] = set()
    lines = tex.splitlines()
    for line in lines:
        body, marker, comment = _split_id(line)
        qid = comment.strip()
        if marker and qid in emitted and emitted[qid] and emitted[qid] in body:
            found.add(qid)
    for qid, text in emitted.items():
        if qid in found or not text:
            continue
        for idx, line in enumerate(lines):
            body, _, _ = _split_id(line)
            if text in body:
                issues.append(
                    Issue(
                        file=file,
                        line=idx + 1,
                        item=qid,
                        message=f"bullet text is in the output without its `% id:{qid}` comment.",
                        fix="end the bullet line in the template with `% id:\\VAR{b.id}`.",
                    )
                )
                break
    return found, issues


def ids_in_tex(tex: str) -> list[str]:
    return re.findall(r"(?<!\\)% id:([A-Za-z0-9-]+\.[A-Za-z0-9-]+)\s*$", tex, flags=re.MULTILINE)


_ID_COMMENT = re.compile(r"(?<!\\)% id:")


def _split_id(line: str) -> tuple[str, str, str]:
    """(text before, marker, comment after) for the first unescaped `% id:` on a line."""
    m = _ID_COMMENT.search(line)
    if m is None:
        return line, "", ""
    return line[: m.start()], m.group(0), line[m.end() :]


def header_of_tex(tex: str, file: str) -> Header | None:
    header, _ = parse_header(tex, file)
    return header


# ---------------------------------------------------------------- context


def format_date(value: str | None, locale: Locale) -> str:
    if not value:
        return ""
    if value == "present":
        return locale.present
    if len(value) == 4:  # the source gave only a year
        return value
    return datetime.strptime(value, "%Y-%m").strftime(locale.date_format)


def _link(raw: str) -> dict[str, str]:
    href = raw if re.match(r"^[a-z][a-z0-9+.-]*:", raw) else f"https://{raw}"
    return {"text": escape(raw), "href": escape_url(href)}


def build_context(
    selection: Selection,
    profile: Profile,
    hat: Hat | None,
    locale: Locale,
    meta: dict[str, str],
) -> dict[str, Any]:
    """Everything a template can see. All strings are LaTeX-escaped exactly once, here."""
    p = profile.person

    def bullets(item: SelectedItem) -> list[dict[str, Any]]:
        return [
            {
                "id": sb.qid,
                "text": escape(sb.text, breakable=True),
                "skills": [escape(profile.skills[s]) for s in sb.bullet.skills],
            }
            for sb in item.bullets
        ]

    def dated(item: SelectedItem) -> dict[str, str]:
        start, end = getattr(item.item, "start", None), getattr(item.item, "end", None)
        return {
            "start": escape(format_date(start, locale)),
            "end": escape(format_date(end, locale)),
            "start_raw": start or "",
            "end_raw": end or "",
        }

    experience = []
    for si in selection.experience:
        e = si.item
        assert isinstance(e, Experience)
        experience.append(
            {
                "id": e.id,
                "title": escape(e.title),
                "org": escape(e.org),
                "location": escape(e.location or ""),
                **dated(si),
                "bullets": bullets(si),
            }
        )
    projects = []
    for si in selection.projects:
        pr = si.item
        assert isinstance(pr, Project)
        link = _link(pr.url) if pr.url else {"text": "", "href": ""}
        projects.append(
            {
                "id": pr.id,
                "name": escape(pr.name),
                "url": link["text"],
                "href": link["href"],
                "stack": escape(pr.stack or ""),
                **dated(si),
                "bullets": bullets(si),
            }
        )
    education = []
    for si in selection.education:
        ed = si.item
        assert isinstance(ed, Education)
        education.append(
            {
                "id": ed.id,
                "degree": escape(ed.degree),
                "org": escape(ed.org),
                "location": escape(ed.location or ""),
                **dated(si),
                "bullets": bullets(si),
            }
        )
    return {
        "person": {
            "name": escape(p.name),
            "email": escape(p.email or ""),
            "phone": escape(p.phone or ""),
            "location": escape(p.location or ""),
            "links": [_link(link) for link in p.links],
            "title_line": escape(hat.title_line if hat else ""),
        },
        "experience": experience,
        "projects": projects,
        "education": education,
        "skills": [escape(s.name) for s in selection.skills],
        "skill_groups": [
            {"name": escape(group), "skills": [escape(s.name) for s in members]}
            for group, members in selection.skill_groups
        ],
        "meta": {
            "hat": escape(meta.get("hat", "")),
            "job_title": escape(meta.get("job_title", "")),
            "build_date": meta.get("build_date", ""),
            "version": meta.get("version", ""),
            "locale": locale.name,
            "cv_word": locale.cv_word,
            "paper": locale.paper,
            "sections": list(selection.sections),
        },
    }
