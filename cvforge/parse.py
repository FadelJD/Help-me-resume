"""profile.cv.txt <-> Profile. The only module that knows the profile text format.

The format is a strict subset of YAML read with ruamel.yaml, so comments and layout survive the
`add` commands. Hats are TOML and are loaded here too, so every input format lives in one place.
"""

from __future__ import annotations

import io
import json as _json
import re
import tomllib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import MarkedYAMLError

from cvforge.errors import CVForgeError, Issue

if TYPE_CHECKING:
    from cvforge.importer import Draft, Src
from cvforge.schema import Bullet, Education, Experience, Hat, Person, Profile, Project

Loc = tuple[str | int, ...]

PROFILE_HEADER = "profile.cv.txt  -  one person, every role, every fact once."


@dataclass(frozen=True)
class SourceMap:
    """Maps a location like ('experience', 0, 'bullets', 1) to its 1-based line in the file."""

    file: str
    lines: dict[Loc, int]
    data: Any

    def line(self, loc: Sequence[str | int]) -> int | None:
        loc = tuple(loc)
        while loc:
            if loc in self.lines:
                return self.lines[loc]
            loc = loc[:-1]
        return None

    def item_id(self, loc: Sequence[str | int]) -> str | None:
        """Qualified id of the deepest item on the path, e.g. 'exp-01.b2'."""
        parts: list[str] = []
        node = self.data
        for key in loc:
            try:
                node = node[key]
            except (KeyError, IndexError, TypeError):
                break
            if isinstance(node, dict) and isinstance(node.get("id"), str):
                parts.append(node["id"])
        return ".".join(parts[:2]) if parts else None


@dataclass(frozen=True)
class ParsedProfile:
    profile: Profile
    source: SourceMap


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 4096
    yaml.preserve_quotes = True
    return yaml


def _walk_lines(node: Any, loc: Loc, out: dict[Loc, int]) -> None:
    if isinstance(node, CommentedMap):
        for key in node:
            line = node.lc.key(key)[0] + 1
            out[(*loc, key)] = line
            _walk_lines(node[key], (*loc, key), out)
    elif isinstance(node, CommentedSeq):
        for idx, child in enumerate(node):
            out[(*loc, idx)] = node.lc.item(idx)[0] + 1
            _walk_lines(child, (*loc, idx), out)


def _plain(node: Any) -> Any:
    if isinstance(node, dict):
        return {str(k): _plain(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_plain(v) for v in node]
    if isinstance(node, str):
        return str(node)
    return node


def _model_at(loc: Loc) -> type[BaseModel] | None:
    model: type[BaseModel] | None = Profile
    path = [p for p in loc if isinstance(p, str)]
    nested: dict[tuple[str, ...], type[BaseModel]] = {
        ("person",): Person,
        ("experience",): Experience,
        ("projects",): Project,
        ("education",): Education,
    }
    for depth in range(len(path), 0, -1):
        key = tuple(path[:depth])
        if key[-1] == "bullets":
            return Bullet
        if key in nested:
            return nested[key]
    return model


def _fix_for(err: dict[str, Any], loc: Loc) -> tuple[str, str]:
    kind = err["type"]
    field = str(loc[-1]) if loc else "file"
    if kind == "extra_forbidden":
        model = _model_at(loc[:-1])
        allowed = ", ".join(model.model_fields) if model else ""
        return (
            f"unknown key `{field}`.",
            f"remove it or fix the spelling; allowed keys here: {allowed}.",
        )
    if kind == "missing":
        return (f"required key `{field}` is missing.", f"add `{field}:` to this item.")
    if field in ("start", "end"):
        extra = " or `present`" if field == "end" else ""
        return (
            f"`{field}` is not a valid date.",
            f"write it as YYYY-MM or YYYY{extra}, e.g. 2025-06.",
        )
    if field == "weight":
        return ("`weight` must be a whole number from 1 to 5.", "use 1 (weak) to 5 (strong).")
    if kind == "string_pattern_mismatch":
        return (
            f"`{field}` is not a valid id.",
            "ids use letters, digits and hyphens, e.g. exp-01 or b2.",
        )
    if kind == "string_too_short":
        return (f"`{field}` is empty.", f"give `{field}` a value or remove the item.")
    return (f"`{field}`: {err['msg']}.", "correct the value to match the format in docs/SPEC.md.")


def _validation_issues(exc: ValidationError, source: SourceMap) -> list[Issue]:
    issues = []
    for err in exc.errors():
        loc = tuple(err["loc"])
        message, fix = _fix_for(dict(err), loc)
        where = ".".join(str(p) if isinstance(p, str) else f"[{p}]" for p in loc)
        issues.append(
            Issue(
                file=source.file,
                line=source.line(loc),
                item=source.item_id(loc),
                message=f"{where.replace('.[', '[')}: {message}",
                fix=fix,
            )
        )
    return issues


def load_raw_text(text: str, file: str) -> Any:
    try:
        data = _yaml().load(text)
    except MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        line = mark.line + 1 if mark is not None else None
        problem = (exc.problem or str(exc)).strip()
        raise CVForgeError(
            [
                Issue(
                    file=file,
                    line=line,
                    message=f"cannot read the file: {problem}.",
                    fix="check indentation and that each key appears once; quote text with `: `.",
                )
            ]
        ) from exc
    if not isinstance(data, CommentedMap):
        raise CVForgeError(
            [
                Issue(
                    file=file,
                    line=1,
                    message="the profile is empty or not a set of `key: value` sections.",
                    fix="start from examples/profile.cv.txt or run `cvforge init`.",
                )
            ]
        )
    return data


def parse_text(text: str, file: str = "profile.cv.txt") -> ParsedProfile:
    text = text.replace("\r\n", "\n")  # files saved on Windows
    data = load_raw_text(text, file)
    lines: dict[Loc, int] = {}
    _walk_lines(data, (), lines)
    source = SourceMap(file=file, lines=lines, data=data)
    try:
        profile = Profile.model_validate(_plain(data))
    except ValidationError as exc:
        raise CVForgeError(_validation_issues(exc, source)) from exc
    return ParsedProfile(profile=profile, source=source)


def load_profile(path: Path) -> ParsedProfile:
    if not path.exists():
        raise CVForgeError(
            [
                Issue(
                    file=str(path),
                    item="--profile",
                    message="profile file not found.",
                    fix="run `cvforge init`, or pass --profile with the right path.",
                )
            ]
        )
    return parse_text(path.read_text(encoding="utf-8"), str(path))


# ---------------------------------------------------------------- hats


def _toml_line(text: str, key: str) -> int | None:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=", re.MULTILINE)
    match = pattern.search(text)
    return text.count("\n", 0, match.start()) + 1 if match else None


def load_hat(path: Path) -> Hat:
    if not path.exists():
        raise CVForgeError(
            [
                Issue(
                    file=str(path),
                    item="--hat",
                    message="hat file not found.",
                    fix="create it (see examples/hats/developer.toml) or check the --hat name.",
                )
            ]
        )
    text = path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CVForgeError(
            [Issue(file=str(path), message=f"invalid TOML: {exc}.", fix="fix the TOML syntax.")]
        ) from exc
    try:
        return Hat.model_validate(data)
    except ValidationError as exc:
        issues = []
        for err in exc.errors():
            loc = tuple(err["loc"])
            key = str(loc[-1]) if loc else ""
            msg = str(err["msg"]).removeprefix("Value error, ")
            named = re.search(r"'([\w-]+)'", msg)  # a validator naming the offending entry
            line = (_toml_line(text, named.group(1)) if named else None) or (
                _toml_line(text, key) if key else None
            )
            if err["type"] == "extra_forbidden":
                fix = f"remove `{key}`; allowed keys: {', '.join(Hat.model_fields)}."
            else:
                fix = "correct the value; see examples/hats/developer.toml."
            issues.append(
                Issue(
                    file=str(path),
                    line=line,
                    item=data.get("name") if isinstance(data.get("name"), str) else None,
                    message=f"`{key}`: {msg}.",
                    fix=fix,
                )
            )
        raise CVForgeError(issues) from exc


# ---------------------------------------------------------------- writing


def _flow(items: Sequence[str]) -> CommentedSeq:
    seq = CommentedSeq(list(items))
    seq.fa.set_flow_style()
    return seq


def _bullet_map(b: Bullet) -> CommentedMap:
    m = CommentedMap()
    m["id"] = b.id
    m["text"] = b.text
    if b.skills:
        m["skills"] = _flow(b.skills)
    m["weight"] = b.weight
    return m


def _item_map(item: BaseModel) -> CommentedMap:
    m = CommentedMap()
    for key, value in item.model_dump(exclude_none=True).items():
        if key == "bullets":
            if not value:
                continue
            m["bullets"] = CommentedSeq(
                [_bullet_map(b) for b in getattr(item, "bullets")]  # noqa: B009
            )
        elif key in ("tags", "links") and isinstance(value, list):
            if value:
                m[key] = _flow(value)
        else:
            m[key] = value
    return m


def dump_profile(profile: Profile) -> str:
    """Canonical text for a whole profile (used by `init`)."""
    root = CommentedMap()
    root["person"] = _item_map(profile.person)
    skills = CommentedMap(profile.skills)
    root["skills"] = skills
    if profile.skill_groups:
        root["skill_groups"] = CommentedMap(
            {g: _flow(members) for g, members in profile.skill_groups.items()}
        )
    for section in ("experience", "projects", "education"):
        root[section] = CommentedSeq([_item_map(i) for i in getattr(profile, section)])
    root.yaml_set_start_comment(PROFILE_HEADER)
    root.yaml_set_comment_before_after_key("skills", before="\nid: name - bullets reference the id")
    for section in ("experience", "projects", "education"):
        root.yaml_set_comment_before_after_key(section, before="\n")
    return dump_raw(root)


def dump_draft(draft: Draft, intro: str) -> str:
    """A draft from `cvforge import` as profile text, one `# source:` comment per value.

    Written by hand rather than through ruamel so each value keeps its comment on its own line.
    Strings are JSON-quoted, which is valid YAML. Missing required values are left empty with a
    TODO comment: the profile then fails validation until they are filled, instead of guessing.
    """
    q = _json.dumps

    def note(src: Src | None) -> str:
        if src is None:
            return "  # TODO no file supplies this"
        marks = (
            f"; TODO confirm (CONFIRM.md #{', #'.join(map(str, src.confirm))})"
            if src.confirm
            else ""
        )
        return f"  # source: {src.source}{marks}"

    def val(src: Src | None) -> str:
        return q(src.value if src is not None else "", ensure_ascii=False)

    out = [f"# {line}" for line in intro.splitlines()]
    out.append("person:")
    out.append(f"  name: {val(draft.name)}{note(draft.name)}")
    for key_ in ("email", "phone"):
        src = getattr(draft, key_)
        if src is not None:
            out.append(f"  {key_}: {val(src)}{note(src)}")
        else:
            out.append(f"  # {key_}: TODO no file supplies this")
    out.append("  # location: TODO no file states where you are based")
    if draft.links:
        out.append("  links:")
        for link in draft.links:
            out.append(f"    - {val(link)}{note(link)}")
    out.append("")
    out.append("skills:")
    for sid, name in draft.skills:
        out.append(f"  {sid}: {val(name)}{note(name)}")
    if draft.groups:
        out.append("")
        out.append("skill_groups:  # how your CV groups the skills, as written")
        for group, ids in draft.groups:
            out.append(f"  {val(group)}: [{', '.join(ids)}]{note(group)}")
    prefixes = {"experience": "exp-", "projects": "prj-", "education": "edu-"}
    for section in ("experience", "projects", "education"):
        items = [i for i in draft.items if i.section == section]
        out.append("")
        if not items:
            out.append(f"{section}: []")
            continue
        out.append(f"{section}:")
        for n, item in enumerate(items, start=1):
            out.append(f"  - id: {prefixes[section]}{n:02d}")
            title_key = {"experience": "title", "projects": "name", "education": "degree"}[section]
            out.append(f"    {title_key}: {val(item.title)}{note(item.title)}")
            if section != "projects":
                out.append(f"    org: {val(item.org)}{note(item.org)}")
            if item.location is not None:
                out.append(f"    location: {val(item.location)}{note(item.location)}")
            if section == "projects" and item.stack is not None:
                out.append(f"    stack: {val(item.stack)}{note(item.stack)}")
            for date_key in ("start", "end"):
                src = getattr(item, date_key)
                if src is not None and src.value:
                    out.append(f"    {date_key}: {val(src)}{note(src)}")
                elif section == "experience" or (section == "education" and date_key == "end"):
                    out.append(f'    {date_key}: ""{note(None)}')
            if item.bullets:
                out.append("    bullets:")
                for k, bullet in enumerate(item.bullets, start=1):
                    out.append(f"      - id: b{k}")
                    out.append(f"        text: {val(bullet.text)}{note(bullet.text)}")
                    if bullet.skills:
                        out.append(
                            f"        skills: [{', '.join(bullet.skills)}]"
                            "  # skill names that appear verbatim in the text"
                        )
                    out.append("        weight: 3  # default; not from your files")
    return "\n".join(out) + "\n"


def dump_raw(data: Any) -> str:
    buf = io.StringIO()
    _yaml().dump(data, buf)
    return buf.getvalue()


def next_id(existing: Sequence[str], prefix: str, width: int = 2) -> str:
    numbers = [
        int(m.group(1))
        for e in existing
        if (m := re.fullmatch(rf"{re.escape(prefix)}(\d+)", e)) is not None
    ]
    n = max(numbers, default=0) + 1
    return f"{prefix}{n:0{width}d}" if width else f"{prefix}{n}"


def _section(data: Any, name: str) -> Any:
    if name not in data or data[name] is None:
        data[name] = CommentedMap() if name == "skills" else CommentedSeq()
    return data[name]


def _iter_items(data: Any) -> Iterator[Any]:
    for section in ("experience", "projects", "education"):
        yield from data.get(section) or []


def append_skill(text: str, file: str, skill_id: str, name: str) -> str:
    data = load_raw_text(text, file)
    skills = _section(data, "skills")
    if skill_id in skills:
        raise CVForgeError(
            [
                Issue(
                    file=file,
                    item=skill_id,
                    message=f"skill id `{skill_id}` already exists ({skills[skill_id]}).",
                    fix="pick another id, or edit the existing entry by hand.",
                )
            ]
        )
    skills[skill_id] = name
    return dump_raw(data)


def append_item(text: str, file: str, section: str, item: Experience | Project | Education) -> str:
    data = load_raw_text(text, file)
    seq = _section(data, section)
    if any(i.get("id") == item.id for i in seq):
        raise CVForgeError(
            [
                Issue(
                    file=file,
                    item=item.id,
                    message=f"id `{item.id}` already exists in {section}.",
                    fix="omit --id to get the next free id.",
                )
            ]
        )
    seq.append(_item_map(item))
    return dump_raw(data)


def append_bullet(text: str, file: str, item_id: str, bullet: Bullet) -> str:
    data = load_raw_text(text, file)
    for item in _iter_items(data):
        if item.get("id") == item_id:
            if "bullets" not in item or item["bullets"] is None:
                item["bullets"] = CommentedSeq()
            if any(b.get("id") == bullet.id for b in item["bullets"]):
                raise CVForgeError(
                    [
                        Issue(
                            file=file,
                            item=f"{item_id}.{bullet.id}",
                            message=f"bullet id `{bullet.id}` already exists in {item_id}.",
                            fix="omit --id to get the next free id.",
                        )
                    ]
                )
            item["bullets"].append(_bullet_map(bullet))
            return dump_raw(data)
    known = ", ".join(str(i.get("id")) for i in _iter_items(data)) or "none yet"
    raise CVForgeError(
        [
            Issue(
                file=file,
                item=item_id,
                message=f"no role, project or education item with id `{item_id}`.",
                fix=f"use one of: {known}.",
            )
        ]
    )


def item_ids(text: str, file: str, section: str) -> list[str]:
    data = load_raw_text(text, file)
    return [str(i.get("id")) for i in (data.get(section) or [])]


def bullet_ids(text: str, file: str, item_id: str) -> list[str]:
    data = load_raw_text(text, file)
    for item in _iter_items(data):
        if item.get("id") == item_id:
            return [str(b.get("id")) for b in (item.get("bullets") or [])]
    return []


# ---------------------------------------------------------------- confirm: `# TODO confirm` lines

_TODO_CONFIRM = re.compile(r"TODO confirm \(CONFIRM\.md (#\d+(?:,\s*#\d+)*)\)")
_LINE_HEAD = re.compile(
    r"^(?P<head>[ \t]*(?:-[ \t]+)?"
    r"(?:(?:\"(?:[^\"\\]|\\.)*\"|'(?:[^']|'')*'|[^\s#\"'\-\[{][^#]*?|-[^\s#][^#]*?):(?:[ \t]+|$))?)"
    r"(?P<rest>\S.*)$"
)


@dataclass(frozen=True)
class ValueLine:
    """One `key: value  # comment` (or `- value  # comment`) line, split where it can change."""

    head: str  # indent, list dash and key, up to the value
    value: str
    gap: str  # the spaces between the value and the comment
    comment: str  # from `#` to the end of the line, or ""


def split_value_line(line: str) -> ValueLine | None:
    """The single-line string value of a profile line, or None when it is not one."""
    m = _LINE_HEAD.match(line)
    if m is None:
        return None
    rest = m.group("rest")
    if rest.startswith("#"):
        return None  # a comment line, or a key with no value
    if rest.startswith('"'):
        try:
            value, end = _json.JSONDecoder().raw_decode(rest)
        except ValueError:
            return None
        if not isinstance(value, str):
            return None
    elif rest.startswith("'"):
        quoted = re.match(r"'((?:[^']|'')*)'", rest)
        if quoted is None:
            return None
        value, end = quoted.group(1).replace("''", "'"), quoted.end()
    else:
        if rest[0] in "[{&*!|>%@`":
            return None  # a list, an anchor, a block scalar: not a value to rewrite in place
        cut = re.search(r"[ \t]#", rest)
        value = (rest[: cut.start()] if cut else rest).rstrip()
        end = len(value)
        if value.endswith(":"):
            return None  # a key whose value is on the lines below
    tail = re.fullmatch(r"([ \t]*)(#.*)?", rest[end:])
    if tail is None:
        return None
    return ValueLine(m.group("head"), value, tail.group(1), tail.group(2) or "")


@dataclass(frozen=True)
class ConfirmLine:
    """A profile line marked `# TODO confirm (CONFIRM.md #N)` by `cvforge import`."""

    line: int  # 1-based
    numbers: tuple[int, ...]
    where: str  # e.g. person.phone, exp-01 start, exp-01.b2 text
    value: str | None  # None when the line holds no single-line value to rewrite
    sources: str


def _describe(loc: Loc, source: SourceMap) -> str:
    item = source.item_id(loc)
    keys = [k for k in loc if isinstance(k, str)]
    if item is not None and keys:
        return f"{item} {keys[-1]}"
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else part)
    return out


def _line_paths(text: str, file: str) -> dict[int, str]:
    """1-based line -> where on that line (the deepest key that starts there)."""
    try:
        data = load_raw_text(text, file)
    except CVForgeError:
        return {}
    locs: dict[Loc, int] = {}
    _walk_lines(data, (), locs)
    deepest: dict[int, Loc] = {}
    for loc, line in locs.items():
        if line not in deepest or len(loc) > len(deepest[line]):
            deepest[line] = loc
    source = SourceMap(file=file, lines=locs, data=data)
    return {line: _describe(loc, source) for line, loc in deepest.items()}


def _todo_numbers(comment: str) -> tuple[int, ...]:
    m = _TODO_CONFIRM.search(comment)
    return tuple(int(n) for n in re.findall(r"\d+", m.group(1))) if m else ()


def confirm_lines(text: str, file: str) -> list[ConfirmLine]:
    """Every line still carrying `TODO confirm`, in file order."""
    text = text.replace("\r\n", "\n")
    paths: dict[int, str] | None = None
    out: list[ConfirmLine] = []
    for n, raw in enumerate(text.split("\n"), start=1):
        if "TODO confirm" not in raw:
            continue
        split = split_value_line(raw)
        if split is not None:
            comment, value = split.comment, split.value
        elif raw.lstrip().startswith("#"):
            continue  # commented out by hand: nothing left to confirm on it
        else:
            hash_at = raw.find("#")
            comment, value = (raw[hash_at:] if hash_at >= 0 else ""), None
        numbers = _todo_numbers(comment)
        if not numbers:
            continue
        if paths is None:
            paths = _line_paths(text, file)
        source = re.search(r"#\s*source:\s*([^;]*)", comment)
        out.append(
            ConfirmLine(
                line=n,
                numbers=numbers,
                where=paths.get(n, f"line {n}"),
                value=value,
                sources=source.group(1).strip() if source else "",
            )
        )
    return out


def set_confirmed(text: str, file: str, line: int, number: int, value: str, stamp: str) -> str:
    """`text` with `value` written on `line`, its comment now `# source: <stamp>`.

    Only that line changes; every other byte, line endings included, stays as it was. Other
    TODO confirm numbers on the same line stay pending.
    """
    parts = re.split(r"(?<=\n)", text)
    raw = parts[line - 1]
    body = raw.rstrip("\r\n")
    ending = raw[len(body) :]
    split = split_value_line(body)
    numbers = _todo_numbers(split.comment) if split is not None else ()
    if split is None or number not in numbers:
        raise CVForgeError(
            [
                Issue(
                    file=file,
                    line=line,
                    item=f"CONFIRM.md #{number}",
                    message="this line holds no single-line value marked TODO confirm, so "
                    "confirm cannot rewrite it in place.",
                    fix="edit the line by hand: write the value, then replace the comment with "
                    "`# source: user` and today's date.",
                )
            ]
        )
    rest = [k for k in numbers if k != number]
    comment = f"# source: {stamp}"
    if rest:
        comment += f"; TODO confirm (CONFIRM.md #{', #'.join(map(str, rest))})"
    quoted = _json.dumps(value, ensure_ascii=False)
    parts[line - 1] = f"{split.head}{quoted}{split.gap or '  '}{comment}{ending}"
    return "".join(parts)
