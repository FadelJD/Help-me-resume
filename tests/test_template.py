from __future__ import annotations

from pathlib import Path

import pytest

from cvforge.config import LOCALES
from cvforge.errors import CVForgeError
from cvforge.parse import load_hat, load_profile
from cvforge.select import select
from cvforge.template import (
    analyze,
    build_context,
    check_traceability,
    format_date,
    ids_in_tex,
    lint,
    parse_header,
    render,
    validate_template,
)

from .conftest import EXAMPLES, FIXTURES, TEMPLATES

HEADER = "%% cvforge-template v1\n%% sections: experience, skills\n"
ALL = ["experience", "projects", "skills", "education"]


def _validate(tmp_path: Path, body: str, header: str = HEADER) -> list[str]:
    f = tmp_path / "t.tex"
    f.write_text(header + body)
    _, report = validate_template(f, ALL)
    return [str(i) for i in report.issues if i.severity == "error"]


def test_minimal_template_is_valid() -> None:
    _, report = validate_template(TEMPLATES / "minimal.tex", ALL)
    assert report.ok
    assert report.issues == []
    assert report.lint == []
    assert report.will_fill == ALL
    assert report.header is not None and report.header.max_bullets == 5


def test_missing_header_is_refused(tmp_path: Path) -> None:
    errs = _validate(tmp_path, "\\documentclass{article}", header="")
    assert any("header block" in e for e in errs)


def test_header_unknown_section_suggests(tmp_path: Path) -> None:
    header, issues = parse_header("%% cvforge-template v1\n%% sections: experiance\n", "t")
    assert header is not None and header.sections == ()
    assert "Did you mean `experience`" in issues[0].fix


def test_header_unknown_key() -> None:
    _, issues = parse_header("%% cvforge-template v1\n%% sections: skills\n%% colour: red\n", "t")
    assert issues and issues[0].line == 3


def test_unknown_field_names_line_and_suggestion(tmp_path: Path) -> None:
    errs = _validate(
        tmp_path, "\\BLOCK{for job in experience}\n\\VAR{job.titel}\n\\BLOCK{endfor}\n"
    )
    assert len(errs) == 1
    assert "t.tex:4" in errs[0] and "experience.titel" in errs[0]
    assert "experience.title" in errs[0]


def test_unknown_root(tmp_path: Path) -> None:
    errs = _validate(tmp_path, "\\VAR{persn.name}\n")
    assert "Did you mean `person`" in errs[0]


def test_undeclared_section(tmp_path: Path) -> None:
    errs = _validate(tmp_path, "\\BLOCK{for p in projects}\\VAR{p.name}\\BLOCK{endfor}\n")
    assert any("`projects` is not in `%% sections:`" in e for e in errs)


def test_undeclared_feature(tmp_path: Path) -> None:
    errs = _validate(tmp_path, "\\BLOCK{for l in person.links}\\VAR{l.text}\\BLOCK{endfor}\n")
    assert any("person.links" in e and "supports" in e for e in errs)


def test_bullet_without_id_is_refused() -> None:
    _, report = validate_template(FIXTURES / "template_noid.tex", ALL)
    assert not report.ok
    assert report.issues[0].line == 7


def test_syntax_error_has_line(tmp_path: Path) -> None:
    errs = _validate(tmp_path, "\\BLOCK{for job in experience}\n\\VAR{job.title}\n")
    assert errs and "syntax" in errs[0]


def test_macros_and_set_are_understood(tmp_path: Path) -> None:
    body = (
        "\\BLOCK{macro row(x)}\\VAR{x}\\BLOCK{endmacro}\n"
        "\\BLOCK{set jobs = experience}\n"
        "\\BLOCK{for job in jobs}\\VAR{row(job.title)} \\VAR{loop.index}\\BLOCK{endfor}\n"
        "\\VAR{skills|join(', ')}\n"
    )
    assert _validate(tmp_path, body) == []


def test_analyze_resolves_loop_paths() -> None:
    uses, _ = analyze(
        "\\BLOCK{for j in experience}\\BLOCK{for b in j.bullets}\\VAR{b.text}"
        "\\BLOCK{endfor}\\BLOCK{endfor}",
        "t",
    )
    assert "experience.bullets.text" in {u.path for u in uses}


def test_lint_flags_icons_and_columns() -> None:
    icons = lint((FIXTURES / "template_icons.tex").read_text(), "i")
    twocol = lint((FIXTURES / "template_twocol.tex").read_text(), "t")
    assert any("icon font" in i.message for i in icons)
    assert any("two-column" in i.message for i in twocol)
    assert all(i.severity == "warning" for i in icons + twocol)


def test_lint_flags_photo_header_and_fontspec() -> None:
    src = "\\usepackage{fontspec}\n\\fancyhead[L]{Jane}\n\\includegraphics{me.jpg}\n"
    messages = " ".join(i.message for i in lint(src, "x"))
    assert "includegraphics" in messages and "headers/footers" in messages
    assert "Ligatures=NoCommon" in messages


def test_lint_ignores_commented_lines() -> None:
    assert lint("% \\usepackage{fontawesome5}\n", "x") == []


def test_format_date() -> None:
    assert format_date("2025-06", LOCALES["th"]) == "Jun 2025"
    assert format_date("present", LOCALES["us"]) == "Present"
    assert format_date(None, LOCALES["th"]) == ""


def _context() -> dict[str, object]:
    profile = load_profile(EXAMPLES / "profile.cv.txt").profile
    hat = load_hat(EXAMPLES / "hats" / "developer.toml")
    sel = select(profile, hat, None, 5)
    return build_context(sel, profile, hat, LOCALES["th"], {"hat": "developer"})


def test_context_strings_are_escaped_once() -> None:
    ctx = _context()
    texts = [b["text"] for job in ctx["experience"] for b in job["bullets"]]  # type: ignore[attr-defined]
    assert any(r"C\# code samples" in t and r"\&" in t for t in texts)
    assert not any(r"\\#" in t for t in texts)
    assert ctx["person"]["links"][0]["href"] == "https://github.com/janedoe"  # type: ignore[index]


def test_render_and_traceability() -> None:
    text = (TEMPLATES / "minimal.tex").read_text()
    ctx = _context()
    tex = render(text, ctx, "minimal.tex")
    ids = ids_in_tex(tex)
    assert "exp-01.b2" in ids and len(ids) == len(set(ids))
    emitted = {
        b["id"]: b["text"]
        for sec in ("experience", "projects")
        for item in ctx[sec]  # type: ignore[attr-defined]
        for b in item["bullets"]
    }
    found, issues = check_traceability(tex, emitted, "minimal.tex")
    assert issues == [] and found == set(emitted)


def test_traceability_catches_missing_id() -> None:
    tex = "\\item Shipped it.\n"
    _, issues = check_traceability(tex, {"exp-01.b1": "Shipped it."}, "t")
    assert issues and issues[0].item == "exp-01.b1"


def test_render_undefined_value_is_reported() -> None:
    with pytest.raises(CVForgeError):
        render("\\VAR{nothing.here}", {}, "t")


def test_right_aligned_dates_lint_warning() -> None:
    right = lint((TEMPLATES / "minimal-right-dates.tex").read_text(), "r")
    assert any("right-aligned dates" in i.message for i in right)
    assert all(i.severity == "warning" for i in right)
    assert not any(
        "right-aligned" in i.message for i in lint((TEMPLATES / "minimal.tex").read_text(), "m")
    )


def test_right_dates_template_is_valid() -> None:
    _, report = validate_template(TEMPLATES / "minimal-right-dates.tex", ALL)
    assert report.ok


def test_fixed_text_is_everything_outside_tags() -> None:
    _, report = validate_template(TEMPLATES / "minimal.tex", ALL)
    assert [t for _, t in report.fixed_text] == ["Experience", "Projects", "Skills", "Education"]
    assert "person.name" in report.fields
    assert "fixed_text" in report.to_dict() and "filled_fields" in report.to_dict()


def test_fixed_text_flags_personal_facts(tmp_path: Path) -> None:
    body = (
        "\\documentclass{article}\n\\begin{document}\n"
        "{\\Large Jane Doe}\\\\ % hard-coded name\n"
        "\\href{mailto:jane@example.com}{jane@example.com} \\vspace{4pt}\n"
        "\\textbf{Profile:} \\VAR{person.title_line}\n"
        "\\BLOCK{for job in experience}\\VAR{job.title}\\BLOCK{endfor}\n"
        "\\end{document}\n"
    )
    f = tmp_path / "t.tex"
    f.write_text(HEADER + body)
    _, report = validate_template(f, ALL)
    texts = dict(report.fixed_text)
    assert texts[5] == "Jane Doe"
    assert texts[6] == "jane@example.com"  # the href target and \vspace are not printed
    assert texts[7] == "Profile:"
    assert 8 not in texts  # only tags on that line
    warned = [i for i in report.issues if "personal fact" in i.message]
    assert [i.line for i in warned] == [6]
    assert report.ok  # a warning, not an error


def test_visible_text() -> None:
    from cvforge.template import visible_text

    assert visible_text("\\section*{Work \\& Projects}") == "Work & Projects"
    assert visible_text("\\textcolor{gray}{Skills} \\hspace{1em}") == "Skills"
    assert visible_text("\\begin{tabular*}{\\textwidth}{l@{\\extracolsep{\\fill}}r}") == ""


CORPUS_T = TEMPLATES.parent / "tests" / "fixtures" / "templates"


def _lint_messages(name: str) -> str:
    return " ".join(i.message for i in lint((CORPUS_T / name / "template.tex").read_text(), name))


def test_lint_ot1_encoding_from_jakes_resume() -> None:
    assert "OT1" in _lint_messages("jakes-resume")
    assert "OT1" not in " ".join(
        i.message for i in lint((TEMPLATES / "minimal.tex").read_text(), "m")
    )


def test_lint_side_by_side_minipages_from_deedy() -> None:
    messages = _lint_messages("deedy-resume")
    assert "two-column" in messages
    assert "right-aligned" not in messages  # the \hfill between the boxes is not a date


def test_lint_ignores_empty_footer_and_unused_icon_package() -> None:
    messages = _lint_messages("jakes-resume")  # \fancyfoot{} and an unused marvosym
    assert "headers/footers" not in messages and "icon font" not in messages


def test_lint_icon_package_used() -> None:
    src = "\\usepackage{fontawesome5}\n\\begin{document}\n\\faGithub\\ x\n"
    assert any("icon font" in i.message for i in lint(src, "x"))


def test_lint_fontspec_accepts_commonoff() -> None:
    src = "\\usepackage{fontspec}\n\\setmainfont{Lato}[Ligatures=CommonOff]\n"
    assert not any("fontspec" in i.message for i in lint(src, "x"))


def test_regression_user_text_containing_id_marker() -> None:
    # Found by the escaper fuzz: text "50% id:x" escapes to "50\\% id:x", which the
    # traceability split mistook for the id comment.
    tex = "\\item Cut 50\\% id:x of costs % id:exp-01.b1\n"
    found, issues = check_traceability(tex, {"exp-01.b1": "Cut 50\\% id:x of costs"}, "t")
    assert issues == [] and found == {"exp-01.b1"}
    assert ids_in_tex(tex) == ["exp-01.b1"]
