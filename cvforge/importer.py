"""cvforge import: a draft profile from an existing CV, deterministically (no model, no network).

PDFs are read with `pdftotext -layout`, which keeps a row's left and right parts on one line
(title ... dates, employer ... location), plus the PDF's link targets. LaTeX sources are read
from the macros of the widespread Jake's Resume family (`\\resumeSubheading`, `\\resumeItem`, ...)
and the document header. Both become the same blocks (sections, rows, lines, bullets), which one
structurer turns into a draft. Text is kept verbatim; every value carries its source ("cv-b p.1"
or "cv-d.tex:93"); anything missing is left as TODO, never guessed.

Several drafts merge into one: the union of facts, deduplicated by normalised text, earlier files
taking precedence. Disagreements (a date, a title, a second wording of a bullet) are recorded as
confirmations, not resolved.
"""

from __future__ import annotations

import re
import subprocess
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from cvforge.errors import CVForgeError, Issue

# ---------------------------------------------------------------- data


@dataclass
class Src:
    value: str
    sources: list[str]
    confirm: list[int] = field(default_factory=list)  # CONFIRM.md entry numbers

    @property
    def source(self) -> str:
        return ", ".join(self.sources)


@dataclass
class DraftBullet:
    text: Src
    skills: list[str] = field(default_factory=list)


@dataclass
class DraftItem:
    section: str  # experience | projects | education
    title: Src | None = None  # experience title, project name, or education degree
    org: Src | None = None
    location: Src | None = None
    start: Src | None = None
    end: Src | None = None
    stack: Src | None = None
    bullets: list[DraftBullet] = field(default_factory=list)


@dataclass
class Draft:
    label: str
    name: Src | None = None
    email: Src | None = None
    phone: Src | None = None
    links: list[Src] = field(default_factory=list)
    title_line: Src | None = None
    skills: list[tuple[str, Src]] = field(default_factory=list)  # (id, name)
    groups: list[tuple[Src, list[str]]] = field(default_factory=list)  # (group name, ids)
    items: list[DraftItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Confirm:
    number: int
    what: str
    options: list[tuple[str, str]]  # (value, sources)
    kept: str  # which value the profile carries until confirmed


@dataclass
class Block:
    kind: str  # section | row | line | bullet
    left: str
    right: str
    source: str
    indent: int = 0


# ---------------------------------------------------------------- dates

_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ]
    )
    for m in names
}
_ONE_DATE = r"(?:(?:[A-Za-z]{3,9}\.?\s+)?(?:19|20)\d{2}|present|current|now|ongoing)"
DATE_RANGE = re.compile(
    rf"^\s*(?P<start>{_ONE_DATE})(?:\s*(?:[\u2013\u2014-]+|to)\s*(?P<end>{_ONE_DATE}))?\s*$",
    re.IGNORECASE,
)


def parse_date(text: str) -> str | None:
    """'Oct 2025' -> '2025-10', '2021' -> '2021', 'Present' -> 'present'; None if unreadable."""
    t = text.strip().rstrip(".")
    if t.lower() in ("present", "current", "now", "ongoing"):
        return "present"
    m = re.fullmatch(r"(?:([A-Za-z]{3,9})\.?\s+)?((?:19|20)\d{2})", t)
    if not m:
        return None
    if m.group(1) is None:
        return m.group(2)
    month = _MONTHS.get(m.group(1).lower())
    return f"{m.group(2)}-{month:02d}" if month else None


def split_dates(text: str) -> tuple[str | None, str | None] | None:
    m = DATE_RANGE.match(text)
    if not m:
        return None
    start = parse_date(m.group("start"))
    end = parse_date(m.group("end")) if m.group("end") else None
    if start is None:
        return None
    return start, end


# ---------------------------------------------------------------- normalising


def norm(text: str) -> str:
    """Comparison key: NFKC, straight quotes, plain dashes, no case or spacing differences."""
    t = unicodedata.normalize("NFKC", text)
    t = t.translate({0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"', 0x2013: "-", 0x2014: "-"})
    t = re.sub(r"\s+", " ", t).strip().rstrip(".").casefold()
    return t


def key(text: str) -> str:
    """Looser key for names: drop parentheticals and everything but letters and digits."""
    t = re.sub(r"\([^)]*\)", "", norm(text))
    return re.sub(r"[^0-9a-z]+", "", t)


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a).split(), norm(b).split(), autojunk=False).ratio()


def skill_id(name: str, taken: set[str]) -> str:
    t = name.casefold().replace("c#", "csharp").replace("c++", "cpp").replace("f#", "fsharp")
    t = re.sub(r"[^0-9a-z]+", "-", t).strip("-") or "skill"
    candidate, n = t, 2
    while candidate in taken:
        candidate, n = f"{t}-{n}", n + 1
    return candidate


def mentions(text: str, name: str) -> bool:
    """Case-sensitive whole-term match: "Git" misses "GitLab"; "SQL" hits "SQL-based"."""
    return re.search(rf"(?<![\w.#+]){re.escape(name)}(?![\w#+])", text) is not None


# ---------------------------------------------------------------- PDF


_BULLET = re.compile(r"^[\u2013\u2022\u25e6\u2219\u00b7\u25aa*-]\s+")
_HEADINGS = {
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "employment": "experience",
    "education": "education",
    "projects": "projects",
    "personal projects": "projects",
    "technical skills": "skills",
    "skills": "skills",
}


def pdf_blocks(path: Path, label: str) -> tuple[list[Block], list[str]]:
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=True,
            timeout=60,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CVForgeError(
            [
                Issue(
                    file=str(path),
                    item="pdftotext",
                    message=f"could not read the PDF text: {exc}.",
                    fix="install poppler-utils (pdftotext) and check the file opens.",
                )
            ]
        ) from exc
    blocks: list[Block] = []
    for page_no, page in enumerate(out.split("\f"), start=1):
        src = f"{label} p.{page_no}"
        for raw in page.splitlines():
            if not raw.strip():
                continue
            line = unicodedata.normalize("NFKC", raw.rstrip())
            indent = len(line) - len(line.lstrip())
            body = line.strip()
            parts = re.split(r"\s{3,}", body)
            if _BULLET.match(body):
                blocks.append(Block("bullet", _BULLET.sub("", body), "", src, indent))
            elif indent == 0 and body.casefold() in _HEADINGS:
                blocks.append(Block("section", body, "", src, indent))
            elif len(parts) >= 2:
                blocks.append(Block("row", " ".join(parts[:-1]), parts[-1], src, indent))
            else:
                blocks.append(Block("line", body, "", src, indent))
    return blocks, pdf_links(path)


def pdf_links(path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - pypdf ships with cvforge[check]
        return []
    uris: list[str] = []
    for page in PdfReader(str(path)).pages:
        for annot in page.get("/Annots") or []:
            obj = annot.get_object()
            action = obj.get("/A")
            if action is not None and action.get_object().get("/URI"):
                uris.append(str(action.get_object()["/URI"]))
    return uris


# ---------------------------------------------------------------- LaTeX

_TEXT_CMDS = ("textbf", "textit", "emph", "underline", "textsc", "texttt", "textrm", "textsf")


def _group(s: str, i: int) -> tuple[str, int]:
    """Content of the {...} group starting at s[i] (after optional spaces), and the index after."""
    while i < len(s) and s[i] in " \t\n":
        i += 1
    if i >= len(s) or s[i] != "{":
        return "", i
    depth, j = 0, i
    while j < len(s):
        if s[j] == "\\":
            j += 2
            continue
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[i + 1 : j], j + 1
        j += 1
    return s[i + 1 :], len(s)


def tex_to_text(s: str, links: list[str] | None = None) -> str:
    """Plain text a fragment of CV LaTeX prints. `links` collects \\href targets."""
    out = s
    while (m := re.search(r"\\href\s*\{", out)) is not None:
        url, j = _group(out, m.end() - 1)
        text, k = _group(out, j)
        if links is not None:
            links.append(url)
        out = out[: m.start()] + text + out[k:]
    for cmd in _TEXT_CMDS:
        while (m := re.search(rf"\\{cmd}\s*\{{", out)) is not None:
            inner, j = _group(out, m.end() - 1)
            out = out[: m.start()] + inner + out[j:]
    out = re.sub(r"\\(vspace|hspace)\*?\s*\{[^}]*\}", "", out)
    # Only \\ and blank lines break lines; a source newline is a space, as in TeX.
    out = re.sub(r"\n[ \t]*\n", r"\\\\", out).replace("\n", " ")
    out = out.replace("$|$", "|").replace("\\\\", "\n")
    for a, b in (("\\%", "%"), ("\\&", "&"), ("\\#", "#"), ("\\_", "_"), ("\\$", "$")):
        out = out.replace(a, b)
    out = out.replace("---", "\u2014").replace("--", "\u2013").replace("~", " ")
    out = re.sub(r"\\[A-Za-z]+\*?", "", out)  # size and style switches: \Huge \small \scshape
    out = out.replace("{", "").replace("}", "")
    lines = [" ".join(line.split()) for line in out.split("\n")]
    return "\n".join(line for line in lines if line)


def _strip_comments(text: str) -> str:
    return "\n".join(re.split(r"(?<!\\)%", line, maxsplit=1)[0] for line in text.splitlines())


_TEX_CMD = re.compile(
    r"\\(?:(section\*?|resumeSubheading|resumeProjectHeading|resumeSubSubheading|resumeItem"
    r"|textbf)\b|(begin\{center\}))"
)


def tex_blocks(path: Path, label: str) -> tuple[list[Block], list[str]]:
    raw = path.read_text(encoding="utf-8")
    text = _strip_comments(raw)
    start = text.find("\\begin{document}")
    end = text.find("\\end{document}")
    if start < 0:
        raise CVForgeError(
            [
                Issue(
                    file=str(path),
                    item="\\begin{document}",
                    message="no \\begin{document}, so there is no CV body to import.",
                    fix="pass the main .tex file of the CV.",
                )
            ]
        )
    body_start = start + len("\\begin{document}")
    blocks: list[Block] = []
    links: list[str] = []
    section = ""
    i = body_start
    stop = end if end > 0 else len(text)

    def src(pos: int) -> str:
        return f"{label}:{text.count(chr(10), 0, pos) + 1}"

    while (m := _TEX_CMD.search(text, i, stop)) is not None:
        cmd, pos = m.group(1) or m.group(2), m.start()
        j = m.end()
        if cmd == "begin{center}":
            close = text.find("\\end{center}", j)
            for line in tex_to_text(text[j:close], links).split("\n"):
                blocks.append(Block("line", line, "", src(pos), 20))
            i = close + len("\\end{center}")
            continue
        if cmd.startswith("section"):
            name, j = _group(text, j)
            section = tex_to_text(name).casefold()
            blocks.append(Block("section", tex_to_text(name), "", src(pos)))
        elif cmd == "resumeSubheading":
            args = []
            for _ in range(4):
                a, j = _group(text, j)
                args.append(tex_to_text(a, links))
            blocks.append(Block("row", args[0], args[1], src(pos), 1))
            blocks.append(Block("row", args[2], args[3], src(pos), 1))
        elif cmd in ("resumeProjectHeading", "resumeSubSubheading"):
            a, j = _group(text, j)
            b, j = _group(text, j)
            left, right = tex_to_text(a, links), tex_to_text(b, links)
            if cmd == "resumeProjectHeading" and "|" in left:
                name, _, stack = left.partition("|")
                blocks.append(Block("row", name.strip(), right, src(pos), 1))
                blocks.append(Block("line", stack.strip(), "", src(pos), 1))
            else:
                blocks.append(Block("row", left, right, src(pos), 1))
        elif cmd == "resumeItem":
            a, j = _group(text, j)
            blocks.append(
                Block("bullet", tex_to_text(a, links).replace("\n", " "), "", src(pos), 3)
            )
        elif cmd == "textbf" and "skill" in section:
            group, j2 = _group(text, j)
            items, j3 = _group(text, j2)
            if items.lstrip().startswith(":"):
                blocks.append(
                    Block("line", f"{tex_to_text(group)}{tex_to_text(items)}", "", src(pos), 1)
                )
                j = j3
            else:
                j = j2
        i = max(j, m.end())
    return blocks, links


# ---------------------------------------------------------------- structure


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"^\+?[\d][\d\s().-]{6,}\d$")


def _contact(piece: str, uris: list[str], src: str, draft: Draft) -> None:
    p = piece.strip()
    if not p:
        return
    if _EMAIL.fullmatch(p):
        draft.email = Src(p, [src])
    elif _PHONE.match(p):
        draft.phone = Src(p, [src])
    elif "." in p and " " not in p:
        draft.links.append(Src(re.sub(r"^https?://(www\.)?", "", p).rstrip("/"), [src]))
    else:
        target = next((u for u in uris if p.casefold().replace(" ", "") in u.casefold()), None)
        if target:
            clean = re.sub(r"^https?://(www\.)?", "", target).rstrip("/")
            draft.links.append(Src(clean, [f"{src} (link target of '{p}')"]))
        else:
            draft.notes.append(f"contact text '{p}' ({src}) has no readable link target")


def structure(blocks: list[Block], uris: list[str], label: str) -> Draft:
    draft = Draft(label=label)
    first_section = next((k for k, b in enumerate(blocks) if b.kind == "section"), len(blocks))
    header = blocks[:first_section]
    taken: set[str] = set()
    for k, b in enumerate(header):
        line = " ".join(x for x in (b.left, b.right) if x)
        if k == 0:
            draft.name = Src(line, [b.source])
        elif (
            "|" in line
            or _EMAIL.search(line)
            or _PHONE.match(line)
            or (" " not in line and "." in line)
        ):
            for piece in line.split("|"):
                _contact(piece, uris, b.source, draft)
        elif draft.title_line is None:
            draft.title_line = Src(line, [b.source])
        else:
            draft.notes.append(f"header line '{line}' ({b.source}) was not imported")
    section = ""
    current: DraftItem | None = None
    rows_in_item = 0
    for b in blocks[first_section:]:
        if b.kind == "section":
            section = _HEADINGS.get(b.left.casefold(), "")
            if not section:
                draft.notes.append(f"section '{b.left}' ({b.source}) is not a profile section")
            current, rows_in_item = None, 0
            continue
        if section == "skills":
            line = " ".join(x for x in (b.left, b.right) if x)
            group, sep, items = line.partition(":")
            if not sep and draft.groups:  # a wrapped skills line continues the previous group
                group, items = "", line
                ids = draft.groups[-1][1]
            elif not sep:
                draft.notes.append(f"skills line '{line}' ({b.source}) has no 'Group:' prefix")
                continue
            else:
                ids = []
            for name in (x.strip() for x in items.split(",")):
                if name:
                    sid = skill_id(name, taken)
                    taken.add(sid)
                    draft.skills.append((sid, Src(name, [b.source])))
                    ids.append(sid)
            if group:
                draft.groups.append((Src(group.strip(), [b.source]), ids))
            continue
        if section not in ("experience", "projects", "education"):
            continue
        starts_entry = current is None or bool(current.bullets)
        if (
            b.kind == "line"
            and section != "projects"
            and b.indent <= 2
            and (starts_entry or rows_in_item < 2)
        ):
            b = Block("row", b.left, "", b.source, b.indent)  # a row whose right part is empty
        elif b.kind == "line" and section == "projects" and b.indent <= 2 and starts_entry:
            name, bar, stack = b.left.partition(" | ")  # "Name | tools" heading without a date
            current = DraftItem(section=section, title=Src(name.strip(), [b.source]))
            if bar:
                current.stack = Src(stack.strip(), [b.source])
            draft.items.append(current)
            rows_in_item = 1
            continue
        if (
            b.kind == "row"
            and section == "projects"
            and current is not None
            and not current.bullets
            and current.stack is None
            and split_dates(b.right or "x") is None
        ):
            current.stack = Src(b.left, [b.source])  # a project's tools line, as a second row
            continue
        if b.kind == "row":
            per_item = 1 if section == "projects" else 2
            if current is None or current.bullets or rows_in_item >= per_item:
                current = DraftItem(section=section)
                draft.items.append(current)
                rows_in_item = 0
            rows_in_item += 1
            _row(current, b)
        elif b.kind == "bullet":
            if current is None:
                draft.notes.append(f"bullet '{b.left[:40]}' ({b.source}) has no entry above it")
                continue
            current.bullets.append(DraftBullet(Src(b.left, [b.source])))
        elif b.kind == "line":
            if current is not None and current.bullets and b.indent > 0:
                last = current.bullets[-1].text  # a wrapped bullet continues
                joiner = "" if last.value.endswith("-") else " "
                last.value = f"{last.value}{joiner}{b.left}"
            elif current is not None and section == "projects" and current.stack is None:
                current.stack = Src(b.left, [b.source])
            elif current is not None and section != "projects" and current.title is None:
                current.title = Src(b.left, [b.source])
            else:
                draft.notes.append(f"line '{b.left[:50]}' ({b.source}) was not placed")
    for item in draft.items:
        for bullet in item.bullets:
            bullet.skills = [
                sid for sid, name in draft.skills if mentions(bullet.text.value, name.value)
            ]
    return draft


def _row(item: DraftItem, b: Block) -> None:
    dates = split_dates(b.right) if b.right else None
    if dates is not None:
        start, end = dates
        if item.title is None:
            item.title = Src(b.left, [b.source])
        if end is None and item.section == "projects":
            item.end = Src(start or "", [b.source])
        else:
            item.start = Src(start or "", [b.source])
            item.end = Src(end or start or "", [b.source])
    elif item.section == "projects":
        if item.title is None:
            item.title = Src(b.left, [b.source])
    else:
        if item.org is None:
            item.org = Src(b.left, [b.source])
        elif item.title is None:
            item.title = Src(b.left, [b.source])
        if b.right and item.location is None:
            item.location = Src(b.right, [b.source])


def import_file(path: Path, label: str | None = None) -> Draft:
    label = label or path.stem
    if path.suffix.lower() == ".pdf":
        blocks, uris = pdf_blocks(path, label)
    elif path.suffix.lower() == ".tex":
        blocks, uris = tex_blocks(path, f"{label}.tex")
    else:
        raise CVForgeError(
            [
                Issue(
                    file=str(path),
                    item="FILE",
                    message="import reads .pdf or .tex files.",
                    fix="pass the CV as a PDF, or its LaTeX source.",
                )
            ]
        )
    return structure(blocks, uris, label)


# ---------------------------------------------------------------- merge


@dataclass
class Merged:
    draft: Draft
    confirms: list[Confirm]
    titles: list[Src] = field(default_factory=list)  # title lines under the name, per file


def merge(drafts: list[Draft]) -> Merged:
    """Union of facts; earlier drafts take precedence; disagreements become confirmations."""
    if not drafts:
        raise ValueError("nothing to merge")
    base = drafts[0]
    confirms: list[Confirm] = []
    titles = [d.title_line for d in drafts if d.title_line is not None]

    def disagree(what: str, kept: Src, other: Src) -> None:
        number = len(confirms) + 1
        confirms.append(
            Confirm(
                number, what, [(kept.value, kept.source), (other.value, other.source)], kept.value
            )
        )
        kept.confirm.append(number)

    def field_merge(what: str, mine: Src | None, theirs: Src | None) -> Src | None:
        if theirs is None:
            return mine
        if mine is None:
            return theirs
        if norm(mine.value) == norm(theirs.value):
            mine.sources.extend(s for s in theirs.sources if s not in mine.sources)
        else:
            disagree(what, mine, theirs)
        return mine

    for other in drafts[1:]:
        base.name = field_merge("name", base.name, other.name)
        base.email = field_merge("email", base.email, other.email)
        base.phone = field_merge("phone", base.phone, other.phone)
        for link in other.links:
            match = next((x for x in base.links if norm(x.value) == norm(link.value)), None)
            if match:
                match.sources.extend(s for s in link.sources if s not in match.sources)
            else:
                base.links.append(link)
        _merge_skills(base, other, confirms)
        for item in other.items:
            _merge_item(base, item, confirms, disagree, field_merge)
        base.notes.extend(other.notes)
    return Merged(base, confirms, titles)


def _item_key(item: DraftItem) -> str:
    title = key(item.title.value) if item.title else ""
    if item.section == "projects":
        return f"projects:{title}"
    return f"{item.section}:{title}:{key(item.org.value) if item.org else ''}"


def _merge_item(
    base: Draft,
    item: DraftItem,
    confirms: list[Confirm],
    disagree: Callable[[str, Src, Src], None],
    field_merge: Callable[[str, Src | None, Src | None], Src | None],
) -> None:
    match = next((x for x in base.items if _item_key(x) == _item_key(item)), None)
    if match is None:
        base.items.append(item)
        return
    label = (match.title.value if match.title else match.section)[:60]
    match.title = field_merge(f"{match.section} title '{label}'", match.title, item.title)
    match.org = field_merge(f"organisation of '{label}'", match.org, item.org)
    match.location = field_merge(f"location of '{label}'", match.location, item.location)
    match.start = field_merge(f"start date of '{label}'", match.start, item.start)
    match.end = field_merge(f"end date of '{label}'", match.end, item.end)
    match.stack = field_merge(f"tools line of '{label}'", match.stack, item.stack)
    for bullet in item.bullets:
        same = next(
            (b for b in match.bullets if norm(b.text.value) == norm(bullet.text.value)), None
        )
        if same:
            same.text.sources.extend(s for s in bullet.text.sources if s not in same.text.sources)
            continue
        close = max(
            match.bullets, key=lambda b: similar(b.text.value, bullet.text.value), default=None
        )
        if close is not None and similar(close.text.value, bullet.text.value) >= 0.5:
            disagree(f"a bullet of '{label}' has two wordings", close.text, bullet.text)
        else:
            match.bullets.append(bullet)


def _merge_skills(base: Draft, other: Draft, confirms: list[Confirm]) -> None:
    names = {norm(src.value): sid for sid, src in base.skills}
    taken = {sid for sid, _ in base.skills}
    for _sid, src in other.skills:
        n = norm(src.value)
        if n in names:
            mine = next(s for i, s in base.skills if i == names[n])
            mine.sources.extend(s for s in src.sources if s not in mine.sources)
            continue
        overlap = next(
            (
                (i, s)
                for i, s in base.skills
                if norm(s.value).startswith(n + " ") or n.startswith(norm(s.value) + " ")
            ),
            None,
        )
        if overlap is not None:
            number = len(confirms) + 1
            confirms.append(
                Confirm(
                    number,
                    "a skill is named two ways",
                    [(overlap[1].value, overlap[1].source), (src.value, src.source)],
                    overlap[1].value,
                )
            )
            overlap[1].confirm.append(number)
            continue
        new_id = skill_id(src.value, taken)
        taken.add(new_id)
        src.confirm.append(len(confirms) + 1)
        confirms.append(
            Confirm(
                len(confirms) + 1,
                "a skill appears in only some files, so it has no group yet",
                [(src.value, src.source)],
                src.value,
            )
        )
        base.skills.append((new_id, src))
        names[n] = new_id


def confirm_markdown(merged: Merged, files: list[str]) -> str:
    lines = [
        "# Facts to confirm",
        "",
        f"From `cvforge import` of {', '.join(files)} (earlier files take precedence). The profile "
        "carries the first value of each entry, marked `# TODO confirm`, until you choose.",
        "",
    ]
    for c in merged.confirms:
        lines.append(f"## {c.number}. {c.what}")
        lines.append("")
        for value, sources in c.options:
            marker = " (in the profile now)" if value == c.kept else ""
            lines.append(f"- `{value}` — {sources}{marker}")
        lines.append("")
    if merged.draft.notes:
        lines += ["## Not imported", ""] + [f"- {n}" for n in merged.draft.notes] + [""]
    return "\n".join(lines)
