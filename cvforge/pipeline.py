"""Orchestration used by the CLI. Each function is one command, returns a result, prints nothing."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from cvforge import __version__
from cvforge.check import CheckReport, check
from cvforge.compile import compile_pdf
from cvforge.config import DEFAULT_CONFIG_TEXT, LOCALES, Config, Locale, load_config
from cvforge.errors import CVForgeError, Issue, errors_only
from cvforge.escape import escape
from cvforge.interview import Ask, Confirm, Say, hat_text, run_interview
from cvforge.parse import (
    ParsedProfile,
    append_bullet,
    append_item,
    append_skill,
    bullet_ids,
    dump_profile,
    item_ids,
    load_hat,
    load_profile,
    next_id,
    parse_text,
)
from cvforge.resources import builtin_template, data_path
from cvforge.rewrite import LiteLLMRewriter, Proposal, Rewriter, apply, propose
from cvforge.schema import Bullet, Education, Experience, Hat, Profile, Project, Selection
from cvforge.select import select
from cvforge.template import (
    TemplateReport,
    build_context,
    check_traceability,
    format_date,
    render,
    validate_template,
)
from cvforge.validate import validate_hat, validate_profile


@dataclass
class ValidateResult:
    file: str
    issues: list[Issue] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not errors_only(self.issues)

    @property
    def summary(self) -> str:
        if not self.ok:
            n = len(errors_only(self.issues))
            return f"{self.file}: invalid, {n} error{'s' if n != 1 else ''}"
        parts = ", ".join(f"{v} {k}" for k, v in self.counts.items())
        warn = len(self.issues)
        tail = f", {warn} warning{'s' if warn != 1 else ''}" if warn else ""
        return f"{self.file}: valid ({parts}){tail}"

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "file": self.file,
            "counts": self.counts,
            "issues": [i.to_dict() for i in self.issues],
        }


_LOCALE_OVERRIDE: list[str] = []


def override_locale(locale: str) -> None:
    """--locale beats cvforge.toml for this process."""
    if locale not in LOCALES:
        raise CVForgeError(
            [
                Issue(
                    file="cvforge",
                    item="--locale",
                    message=f"unknown locale `{locale}`.",
                    fix=f"use one of: {', '.join(LOCALES)}.",
                )
            ]
        )
    _LOCALE_OVERRIDE[:] = [locale]


def _config() -> Config:
    cfg = load_config()
    if _LOCALE_OVERRIDE:
        cfg = cfg.model_copy(update={"locale": _LOCALE_OVERRIDE[0]})
    return cfg


def resolve_profile(profile: Path | None, cfg: Config) -> Path:
    return profile if profile is not None else Path(cfg.profile)


def load_valid_profile(path: Path) -> ParsedProfile:
    """Parse and cross-check; raises on any error so later stages only see valid profiles."""
    parsed = load_profile(path)
    errs = errors_only(validate_profile(parsed))
    if errs:
        raise CVForgeError(errs)
    return parsed


def validate(profile: Path | None) -> ValidateResult:
    cfg = load_config()
    path = resolve_profile(profile, cfg)
    parsed = load_profile(path)
    issues = validate_profile(parsed)
    p = parsed.profile
    counts = {
        "roles": len(p.experience),
        "bullets": sum(len(i.bullets) for i in p.all_items()),
        "skills": len(p.skills),
    }
    return ValidateResult(file=str(path), issues=issues, counts=counts)


# ---------------------------------------------------------------- inputs


def resolve_hat(name: str | None, cfg: Config) -> tuple[Hat | None, str]:
    name = name if name is not None else cfg.hat
    if not name:
        return None, ""
    path = (
        Path(name) if name.endswith(".toml") or "/" in name else Path(cfg.hats_dir) / f"{name}.toml"
    )
    return load_hat(path), str(path)


def read_job(job: str | None) -> str | None:
    """A job ad from a file, or from a URL (the only network use outside --rewrite)."""
    if not job:
        return None
    if re.match(r"^https?://", job):
        return fetch_job(job)
    path = Path(job)
    if not path.exists():
        raise CVForgeError(
            [
                Issue(
                    file=job,
                    item="--job",
                    message="job ad not found.",
                    fix="pass a text file or an http(s) URL.",
                )
            ]
        )
    return path.read_text(encoding="utf-8")


class _TextOnly(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript"):
            self._skip += 1
        elif tag in ("p", "br", "li", "div", "h1", "h2", "h3", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextOnly()
    parser.feed(html)
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)


def fetch_job(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": f"cvforge/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode(resp.headers.get_content_charset() or "utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise CVForgeError(
            [
                Issue(
                    file=url,
                    message=f"could not fetch the job ad: {exc}.",
                    fix="save the ad as a .txt file and pass that path instead.",
                )
            ]
        ) from exc
    return html_to_text(body) if "<" in body[:2000] else body


def job_title(job: str | None) -> str:
    if not job:
        return ""
    first = next((line.strip() for line in job.splitlines() if line.strip()), "")
    return first[:100]


def build_date() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    when = datetime.fromtimestamp(int(epoch), tz=UTC) if epoch else datetime.now(tz=UTC)
    return when.strftime("%Y-%m-%d")


# ---------------------------------------------------------------- build


@dataclass
class BuildResult:
    tex: Path
    report_path: Path
    report: dict[str, Any]
    selection: Selection
    warnings: list[Issue] = field(default_factory=list)
    pdf: Path | None = None

    @property
    def summary(self) -> str:
        n_b = len(self.report["emitted"]["bullets"])
        n_d = sum(1 for d in self.selection.dropped if d.kind == "bullet")
        pdf = f", pdf {self.pdf}" if self.pdf else ""
        return f"wrote {self.tex} ({n_b} bullets, {n_d} dropped){pdf}"


@dataclass
class Prepared:
    cfg: Config
    parsed: ParsedProfile
    hat: Hat | None
    hat_file: str
    job: str | None
    selection: Selection
    template_text: str
    template_report: TemplateReport
    template_path: Path
    warnings: list[Issue]


def resolve_template(template: Path | None, cfg: Config) -> Path:
    """A path, or the name of a built-in template (`minimal`, `minimal-right-dates`)."""
    chosen = template if template is not None else (Path(cfg.template) if cfg.template else None)
    if chosen is not None:
        if not chosen.exists():
            builtin = builtin_template(str(chosen))
            if builtin is not None:
                return builtin
        return chosen
    raise CVForgeError(
        [
            Issue(
                file="cvforge.toml",
                item="template",
                message="no template given.",
                fix="pass --template my.tex, or set template = in cvforge.toml.",
            )
        ]
    )


def prepare(
    *,
    profile: Path | None,
    template: Path | None,
    hat: str | None,
    job: str | None,
    max_bullets: int | None,
    need_template: bool = True,
) -> Prepared:
    cfg = _config()
    parsed = load_valid_profile(resolve_profile(profile, cfg))
    hat_model, hat_file = resolve_hat(hat, cfg)
    if hat_model is not None:
        errs = errors_only(validate_hat(hat_model, parsed.profile, hat_file))
        if errs:
            raise CVForgeError(errs)
    job_text = read_job(job)
    warnings: list[Issue] = []
    limit = max_bullets
    template_text, t_report, t_path = "", TemplateReport(file="", header=None), Path()
    if need_template:
        t_path = resolve_template(template, cfg)
        template_text, t_report = validate_template(t_path, parsed.profile.sections_with_items())
        if not t_report.ok:
            raise CVForgeError(errors_only(t_report.issues))
        assert t_report.header is not None
        declared = t_report.header.max_bullets
        if declared is not None and max_bullets is not None and max_bullets > declared:
            warnings.append(
                Issue(
                    file=str(t_path),
                    severity="warning",
                    message=f"--max-bullets {max_bullets} is above the template limit {declared}.",
                    fix="--max-bullets can only lower the template limit; using the template's.",
                )
            )
        candidates = [x for x in (declared, max_bullets) if x is not None]
        limit = min(candidates) if candidates else None
    selection = select(parsed.profile, hat_model, job_text, limit)
    return Prepared(
        cfg,
        parsed,
        hat_model,
        hat_file,
        job_text,
        selection,
        template_text,
        t_report,
        t_path,
        warnings,
    )


def default_output(cfg: Config, profile: Profile, hat: Hat | None) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", profile.person.name.lower()).strip("-") or "cv"
    suffix = f"-{hat.name}" if hat else ""
    return Path(cfg.out_dir) / f"{slug}{suffix}.tex"


def render_selection(prep: Prepared, output: Path | None, job_ref: str | None) -> BuildResult:
    cfg, profile = prep.cfg, prep.parsed.profile
    locale = LOCALES[cfg.locale]
    meta = {
        "hat": prep.hat.name if prep.hat else "",
        "job_title": job_title(prep.job),
        "build_date": build_date(),
        "version": __version__,
    }
    context = build_context(prep.selection, profile, prep.hat, locale, meta)
    tex = render(prep.template_text, context, str(prep.template_path))
    header = prep.template_report.header
    assert header is not None
    shown_sections = set(header.sections)
    emitted = {
        sb.qid: escape(sb.text, breakable=True)
        for si in prep.selection.items()
        if si.section in shown_sections
        for sb in si.bullets
    }
    out_path = output or default_output(cfg, profile, prep.hat)
    found, trace_issues = check_traceability(tex, emitted, str(out_path))
    if trace_issues:
        raise CVForgeError(trace_issues)
    warnings = list(prep.warnings)
    for qid in emitted:
        if qid not in found:
            warnings.append(
                Issue(
                    file=str(prep.template_path),
                    item=qid,
                    severity="warning",
                    message="selected bullet does not appear in the output.",
                    fix="the template does not render bullets for this section; that is allowed.",
                )
            )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(tex, encoding="utf-8")
    report = make_report(prep, out_path, job_ref, locale, found, warnings)
    report_path = out_path.with_suffix(".report.json")
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return BuildResult(out_path, report_path, report, prep.selection, warnings)


def make_report(
    prep: Prepared,
    out_path: Path,
    job_ref: str | None,
    locale: Locale,
    found: set[str],
    warnings: list[Issue],
) -> dict[str, Any]:
    sel, profile = prep.selection, prep.parsed.profile
    header = prep.template_report.header
    assert header is not None
    shown = set(header.sections)
    items = []
    for si in sel.items():
        if si.section not in shown:
            continue
        it = si.item
        items.append(
            {
                "id": it.id,
                "section": si.section,
                "title": getattr(it, "title", None)
                or getattr(it, "name", None)
                or getattr(it, "degree", ""),
                "org": getattr(it, "org", None) or "",
                "start": format_date(getattr(it, "start", None), locale),
                "end": format_date(getattr(it, "end", None), locale),
                "bullets": [
                    {"id": sb.qid, "text": sb.text} for sb in si.bullets if sb.qid in found
                ],
            }
        )
    p = profile.person
    return {
        "tool": "cvforge",
        "version": __version__,
        "built": build_date(),
        "tex": str(out_path),
        "profile": prep.parsed.source.file,
        "template": str(prep.template_path),
        "hat": sel.hat,
        "job": job_ref or "",
        "locale": locale.name,
        "template_fields": prep.template_report.fields,
        "template_header": {
            "sections": list(header.sections),
            "supports": list(header.supports),
            "max_bullets_per_role": header.max_bullets,
            "max_pages": header.max_pages,
            "engine": header.engine,
        },
        "emitted": {
            "person": {"name": p.name, "email": p.email or "", "phone": p.phone or ""},
            "items": items,
            "bullets": sorted(found),
            "skills": [s.name for s in sel.skills] if "skills" in shown else [],
            "skill_evidence": {s.name: [q for q in s.evidence if q in found] for s in sel.skills}
            if "skills" in shown
            else {},
        },
        "ranking": ranking(sel),
        "dropped": [{"id": d.id, "kind": d.kind, "reason": d.reason} for d in sel.dropped],
        "rewrites": [],
        "warnings": [w.to_dict() for w in warnings],
    }


def ranking(sel: Selection) -> list[dict[str, Any]]:
    return [
        {"id": sb.qid, "score": sb.score, **sb.parts, "text": sb.text}
        for si in sel.items()
        for sb in si.bullets
    ]


def build(
    *,
    profile: Path | None,
    template: Path | None,
    hat: str | None,
    job: str | None,
    output: Path | None,
    max_bullets: int | None,
    compile_pdf_too: bool,
) -> BuildResult:
    prep = prepare(profile=profile, template=template, hat=hat, job=job, max_bullets=max_bullets)
    result = render_selection(prep, output, job)
    if compile_pdf_too:
        result.pdf = _compile(prep, result.tex)
    return result


def _engine(prep: Prepared) -> str:
    header = prep.template_report.header
    return header.engine if header else "pdflatex"


def _compile(prep: Prepared, tex: Path) -> Path:
    return compile_pdf(tex, engine=_engine(prep), search=[prep.template_path.parent])


# ---------------------------------------------------------------- explain


@dataclass
class ExplainResult:
    selection: Selection
    hat: str
    job: str

    def to_dict(self) -> dict[str, Any]:
        sel = self.selection
        return {
            "hat": self.hat,
            "job": self.job,
            "sections": sel.sections,
            "max_bullets_per_role": sel.max_bullets,
            "items": [
                {
                    "id": si.item.id,
                    "section": si.section,
                    "bullets": [
                        {"id": sb.qid, "score": sb.score, **sb.parts, "text": sb.text}
                        for sb in si.bullets
                    ],
                }
                for si in sel.items()
            ],
            "skills": [
                {"id": s.id, "name": s.name, "score": s.score, "evidence": s.evidence}
                for s in sel.skills
            ],
            "dropped": [{"id": d.id, "kind": d.kind, "reason": d.reason} for d in sel.dropped],
        }


def explain(
    *,
    profile: Path | None,
    template: Path | None,
    hat: str | None,
    job: str | None,
    max_bullets: int | None,
) -> ExplainResult:
    cfg = load_config()
    use_template = template is not None or bool(cfg.template)
    prep = prepare(
        profile=profile,
        template=template,
        hat=hat,
        job=job,
        max_bullets=max_bullets,
        need_template=use_template,
    )
    return ExplainResult(prep.selection, prep.selection.hat, job or "")


# ---------------------------------------------------------------- template validate


def template_validate(template: Path, profile: Path | None) -> TemplateReport:
    cfg = load_config()
    sections: list[str] | None = None
    path = resolve_profile(profile, cfg)
    if path.exists():
        sections = load_profile(path).profile.sections_with_items()
    _, report = validate_template(template, sections)
    return report


# ---------------------------------------------------------------- init and add


@dataclass
class WriteResult:
    path: Path
    message: str
    written: list[Path] = field(default_factory=list)


def init(
    ask: Ask,
    confirm: Confirm,
    say: Say,
    *,
    directory: Path = Path("."),
    force: bool = False,
    example: bool = False,
) -> WriteResult:
    """Interview, or with `example` copy the fictional sample profile and hats to try the tool."""
    profile_path = directory / "profile.cv.txt"
    config_path = directory / "cvforge.toml"
    for path in (profile_path, config_path):
        if path.exists() and not force:
            raise CVForgeError(
                [
                    Issue(
                        file=str(path),
                        item="--force",
                        message="already exists; init will not overwrite it.",
                        fix="use `cvforge add ...` to extend it, or pass --force to start over.",
                    )
                ]
            )
    if example:
        return _init_example(directory, profile_path, config_path)
    result = run_interview(ask, confirm, say)
    text = dump_profile(result.profile)
    parsed = parse_text(text, str(profile_path))  # never write a profile we cannot read back
    errs = errors_only(validate_profile(parsed))
    if errs:
        raise CVForgeError(errs)
    profile_path.write_text(text, encoding="utf-8")
    config_path.write_text(
        DEFAULT_CONFIG_TEXT.format(template=result.template, hat=result.hat, locale=result.locale),
        encoding="utf-8",
    )
    written = [profile_path, config_path]
    hats_dir = directory / "hats"
    hats_dir.mkdir(exist_ok=True)
    for name, title in result.hats.items():
        hat_path = hats_dir / f"{name}.toml"
        if not hat_path.exists():
            hat_path.write_text(hat_text(name, title, result.profile), encoding="utf-8")
            written.append(hat_path)
    return WriteResult(profile_path, f"wrote {', '.join(str(p) for p in written)}", written)


def _init_example(directory: Path, profile_path: Path, config_path: Path) -> WriteResult:
    sample = data_path("examples", "profile.cv.txt")
    hats = data_path("examples", "hats")
    if sample is None or hats is None:  # pragma: no cover - broken installation
        raise CVForgeError(
            [
                Issue(
                    file="cvforge",
                    item="--example",
                    message="the example profile is missing from this installation.",
                    fix="reinstall cvforge, or run `cvforge init` without --example.",
                )
            ]
        )
    profile_path.write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
    config_path.write_text(
        DEFAULT_CONFIG_TEXT.format(template="minimal", hat="developer", locale="th"),
        encoding="utf-8",
    )
    written = [profile_path, config_path]
    (directory / "hats").mkdir(exist_ok=True)
    for hat in sorted(hats.glob("*.toml")):
        target = directory / "hats" / hat.name
        target.write_text(hat.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(target)
    return WriteResult(
        profile_path,
        f"wrote {', '.join(str(p) for p in written)} (fictional example: Jane Doe)",
        written,
    )


def _write_checked(path: Path, new_text: str) -> None:
    """Validate the would-be file; on error nothing is written, so no line numbers are cited."""
    try:
        parsed = parse_text(new_text, str(path))
    except CVForgeError as exc:
        raise CVForgeError([replace(i, line=None) for i in exc.issues]) from exc
    errs = errors_only(validate_profile(parsed))
    if errs:
        raise CVForgeError([replace(i, line=None) for i in errs])
    path.write_text(new_text, encoding="utf-8")


def _profile_text(profile: Path | None) -> tuple[Path, str]:
    path = resolve_profile(profile, _config())
    if not path.exists():
        raise CVForgeError(
            [Issue(file=str(path), message="profile file not found.", fix="run `cvforge init`.")]
        )
    return path, path.read_text(encoding="utf-8")


def add_skill(profile: Path | None, sid: str, name: str) -> WriteResult:
    path, text = _profile_text(profile)
    _write_checked(path, append_skill(text, str(path), sid, name))
    return WriteResult(path, f"added skill {sid}: {name} to {path}")


def add_role(
    profile: Path | None,
    *,
    title: str,
    org: str,
    start: str,
    end: str,
    location: str | None,
    tags: list[str],
    item_id: str | None,
) -> WriteResult:
    path, text = _profile_text(profile)
    new_id = item_id or next_id(item_ids(text, str(path), "experience"), "exp-")
    try:
        role = Experience(
            id=new_id, title=title, org=org, start=start, end=end, location=location, tags=tags
        )
    except ValidationError as exc:
        raise _arg_error(exc, str(path)) from exc
    _write_checked(path, append_item(text, str(path), "experience", role))
    return WriteResult(path, f"added role {new_id}: {title}, {org} to {path}")


def add_project(
    profile: Path | None, *, name: str, url: str | None, item_id: str | None
) -> WriteResult:
    path, text = _profile_text(profile)
    new_id = item_id or next_id(item_ids(text, str(path), "projects"), "prj-")
    try:
        project = Project(id=new_id, name=name, url=url)
    except ValidationError as exc:
        raise _arg_error(exc, str(path)) from exc
    _write_checked(path, append_item(text, str(path), "projects", project))
    return WriteResult(path, f"added project {new_id}: {name} to {path}")


def add_education(
    profile: Path | None,
    *,
    degree: str,
    org: str,
    start: str | None,
    end: str,
    item_id: str | None,
) -> WriteResult:
    path, text = _profile_text(profile)
    new_id = item_id or next_id(item_ids(text, str(path), "education"), "edu-")
    try:
        edu = Education(id=new_id, degree=degree, org=org, start=start, end=end)
    except ValidationError as exc:
        raise _arg_error(exc, str(path)) from exc
    _write_checked(path, append_item(text, str(path), "education", edu))
    return WriteResult(path, f"added education {new_id}: {degree} to {path}")


def add_bullet(
    profile: Path | None,
    *,
    item_id: str,
    text_: str,
    skills: list[str],
    weight: int,
    bullet_id: str | None,
) -> WriteResult:
    path, text = _profile_text(profile)
    new_id = bullet_id or next_id(bullet_ids(text, str(path), item_id), "b", width=0)
    try:
        bullet = Bullet(id=new_id, text=text_, skills=skills, weight=weight)
    except ValidationError as exc:
        raise _arg_error(exc, str(path)) from exc
    _write_checked(path, append_bullet(text, str(path), item_id, bullet))
    return WriteResult(path, f"added bullet {item_id}.{new_id} to {path}")


def _arg_error(exc: ValidationError, file: str) -> CVForgeError:
    return CVForgeError(
        [
            Issue(
                file=file,
                item=f"--{'-'.join(map(str, e['loc']))}",
                message=f"{str(e['msg']).removeprefix('Value error, ')}.",
                fix="dates are YYYY-MM (end may be present); weight is 1-5; ids use letters, "
                "digits and hyphens.",
            )
            for e in exc.errors()
        ]
    )


# ---------------------------------------------------------------- check


def run_check(
    tex: Path, job: str | None, *, strict: bool, lint_template: bool, semantic: bool
) -> CheckReport:
    if not tex.exists():
        raise CVForgeError(
            [
                Issue(
                    file=str(tex),
                    item="TEX",
                    message="file not found.",
                    fix="run `cvforge build` first; check reads the .tex it wrote.",
                )
            ]
        )
    cfg = _config()
    return check(
        tex,
        read_job(job),
        cfg.thresholds,
        strict=strict,
        lint_template=lint_template,
        semantic=semantic,
        settings=cfg.parsers,
    )


# ---------------------------------------------------------------- tailor


Approve = Callable[[list[Proposal]], None]


def rewriter_from_config(cfg: Config) -> Rewriter:
    if not cfg.llm.model:
        raise CVForgeError(
            [
                Issue(
                    file="cvforge.toml",
                    item="llm.model",
                    message="--rewrite is unavailable: no LLM is configured.",
                    fix='set [llm] model = "<provider>/<model>" in cvforge.toml (e.g. '
                    "\"ollama/llama3\") and pip install 'cvforge[llm]'; everything else works "
                    "without it.",
                )
            ]
        )
    return LiteLLMRewriter(cfg.llm.model, cfg.llm.api_key_env)


def tailor(
    *,
    profile: Path | None,
    template: Path | None,
    hat: str | None,
    job: str,
    output: Path | None,
    max_bullets: int | None,
    compile_pdf_too: bool,
    rewrite: bool,
    approve: Approve,
    rewriter: Rewriter | None = None,
) -> tuple[BuildResult, list[Proposal]]:
    prep = prepare(profile=profile, template=template, hat=hat, job=job, max_bullets=max_bullets)
    proposals: list[Proposal] = []
    if rewrite:
        engine = rewriter or rewriter_from_config(prep.cfg)
        assert prep.job is not None
        proposals = propose(
            prep.selection,
            prep.parsed.profile,
            engine,
            job=prep.job,
            title_line=prep.hat.title_line if prep.hat else "",
        )
        approve(proposals)
        for p in proposals:
            if p.status == "pending":
                p.status = "rejected"
        prep.selection = apply(prep.selection, proposals)
    result = render_selection(prep, output, job)
    if proposals:
        result.report["rewrites"] = [p.to_dict() for p in proposals]
        result.report_path.write_text(
            json.dumps(result.report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    if compile_pdf_too:
        result.pdf = _compile(prep, result.tex)
    return result, proposals
