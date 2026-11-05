"""A single-column Word copy of a build, from the same selection the .tex used.

Parser-safe by construction: one column of paragraphs in built-in styles (Title, Heading 1,
List Bullet, Normal). No tables, text boxes, images, or content in headers or footers. Dates use
the locale's format, as in the .tex, joined with "to" instead of a dash.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentObject
from docx.shared import Cm, Inches

from cvforge.config import Locale
from cvforge.schema import Education, Experience, Hat, Profile, Project, SelectedItem, Selection
from cvforge.template import format_date

HEADINGS = {
    "experience": "Experience",
    "education": "Education",
    "skills": "Skills",
    "projects": "Projects",
}


def date_range(start: str | None, end: str | None, locale: Locale) -> str:
    """'Jun 2023 to Present', or the one date there is."""
    first, last = format_date(start, locale), format_date(end, locale)
    if first and last:
        return f"{first} to {last}"
    return first or last


def _entry(doc: DocumentObject, lead: str, rest: list[str]) -> None:
    para = doc.add_paragraph(style="Normal")
    para.add_run(lead).bold = True
    tail = " | ".join(x for x in rest if x)
    if tail:
        para.add_run(f" | {tail}")


def _item(doc: DocumentObject, si: SelectedItem, locale: Locale, shown: set[str]) -> None:
    it = si.item
    when = date_range(getattr(it, "start", None), getattr(it, "end", None), locale)
    if isinstance(it, Experience):
        _entry(doc, f"{it.title}, {it.org}", [it.location or "", when])
    elif isinstance(it, Project):
        _entry(doc, it.name, [it.url or "", when])
    elif isinstance(it, Education):
        _entry(doc, f"{it.degree}, {it.org}", [it.location or "", when])
    for sb in si.bullets:
        if sb.qid in shown:
            doc.add_paragraph(sb.text, style="List Bullet")


def _page(doc: DocumentObject, locale: Locale) -> None:
    section = doc.sections[0]
    if locale.paper == "letterpaper":
        section.page_width, section.page_height = Inches(8.5), Inches(11)
    else:
        section.page_width, section.page_height = Cm(21), Cm(29.7)
    margin = Cm(1.8)
    section.left_margin = section.right_margin = margin
    section.top_margin = section.bottom_margin = margin


def write_docx(
    path: Path,
    selection: Selection,
    profile: Profile,
    hat: Hat | None,
    locale: Locale,
    sections: list[str],
    bullets: set[str],
    built: str,
) -> Path:
    """Write the .docx. `sections` are the ones the template shows, in the order it shows them;
    `bullets` are the qualified ids the .tex emitted."""
    doc = Document()
    _page(doc, locale)
    p = profile.person
    props = doc.core_properties
    props.title, props.author, props.last_modified_by = p.name, p.name, ""
    props.comments, props.keywords, props.subject = "", "", ""
    when = datetime.strptime(built, "%Y-%m-%d").replace(tzinfo=UTC)
    props.created = props.modified = when
    props.revision = 1

    doc.add_paragraph(p.name, style="Title")
    if hat is not None and hat.title_line:
        doc.add_paragraph(hat.title_line, style="Normal")
    contact = [p.email or "", p.phone or "", p.location or "", *p.links]
    if any(contact):
        doc.add_paragraph(" | ".join(x for x in contact if x), style="Normal")

    for section in sections:
        if section == "skills":
            if not selection.skills:
                continue
            doc.add_paragraph(HEADINGS[section], style="Heading 1")
            if selection.skill_groups:
                for group, members in selection.skill_groups:
                    para = doc.add_paragraph(style="Normal")
                    para.add_run(f"{group}:").bold = True
                    para.add_run(" " + ", ".join(s.name for s in members))
            else:
                doc.add_paragraph(", ".join(s.name for s in selection.skills), style="Normal")
            continue
        items: list[SelectedItem] = getattr(selection, section, [])
        if not items:
            continue
        doc.add_paragraph(HEADINGS[section], style="Heading 1")
        for si in items:
            _item(doc, si, locale, bullets)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path
