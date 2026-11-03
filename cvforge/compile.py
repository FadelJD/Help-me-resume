"""Compile a .tex to PDF: latexmk when available, the engine itself otherwise.

Returns the PDF path or raises with the LaTeX error and its line.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from cvforge.errors import CVForgeError, Issue


def latexmk_available() -> bool:
    """latexmk on PATH, unless CVFORGE_NO_LATEXMK=1 asks for the direct engine runs."""
    if os.environ.get("CVFORGE_NO_LATEXMK") == "1":
        return False
    return shutil.which("latexmk") is not None


ENGINES = {"pdflatex": "-pdf", "xelatex": "-xelatex", "lualatex": "-lualatex"}


def search_env(search: Sequence[Path]) -> dict[str, str]:
    """Environment that lets TeX find a template's own .cls/.sty files and fonts.

    Each folder is searched recursively (`//`); the trailing separator keeps TeX's defaults.
    """
    env = dict(os.environ)
    env.setdefault("max_print_line", "10000")  # TeX Live: do not wrap the log
    if not search:
        return env
    dirs = os.pathsep.join(f"{p.resolve()}//" for p in search) + os.pathsep
    for var in ("TEXINPUTS", "OPENTYPEFONTS", "TTFONTS", "TFMFONTS", "T1FONTS", "ENCFONTS"):
        env[var] = dirs + env.get(var, "")
    return env


_NEEDS_LUA = re.compile(
    r"LuaLaTeX is required|\\RequireLuaTeX|\\directlua|\\luaexec|"
    r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*\b(?:luacode|luatexbase)\b"
)
_NEEDS_UNICODE = re.compile(
    r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*\b"
    r"(?:fontspec|unicode-math|polyglossia|xeCJK|xltxtra)\b"
)
_ANY_ENGINE = re.compile(
    r"\\if(?:xetexorluatex|tutex|luatex|xetex|PDFTeX)\b|\\ifpdftex\b|\\IfTUTeX"
)


@dataclass(frozen=True)
class EngineChoice:
    engines: tuple[str, ...]  # tried in this order
    reason: str


def _code(text: str) -> str:
    return "\n".join(re.split(r"(?<!\\)%", line, maxsplit=1)[0] for line in text.splitlines())


def detect_engine(text: str, search: Sequence[Path] = ()) -> EngineChoice:
    """The engine a template needs, read from its preamble and its local class/package files.

    `%% engine:` in the cvforge header wins. Otherwise: LuaLaTeX when the class or preamble
    requires it; XeLaTeX then LuaLaTeX when fontspec-family packages are loaded unconditionally;
    pdfLaTeX first, falling back to the Unicode engines, when the preamble supports several
    (`\\ifxetexorluatex` and friends); pdfLaTeX otherwise.
    """
    m = re.search(r"^%% engine:\s*(pdflatex|xelatex|lualatex)\s*$", text, flags=re.MULTILINE)
    if m:
        return EngineChoice((m.group(1),), "declared in the template header")
    preamble = _code(text).split("\\begin{document}")[0]
    local = []
    names = re.findall(
        r"\\(?:documentclass|usepackage|RequirePackage)(?:\[[^\]]*\])?\{([^}]*)\}", preamble
    )
    for folder in search:
        for name in (n.strip() for group in names for n in group.split(",")):
            for path in [*folder.rglob(f"{name}.cls"), *folder.rglob(f"{name}.sty")][:1]:
                local.append(_code(path.read_text(encoding="utf-8", errors="replace")))
    blob = "\n".join([preamble, *local])
    if _NEEDS_LUA.search(blob):
        return EngineChoice(("lualatex",), "the class or preamble requires LuaLaTeX")
    conditional = _ANY_ENGINE.search(blob) is not None
    if _NEEDS_UNICODE.search(blob) and not conditional:
        return EngineChoice(
            ("xelatex", "lualatex"), "fontspec-family packages need XeLaTeX or LuaLaTeX"
        )
    if conditional:
        return EngineChoice(
            ("pdflatex", "lualatex", "xelatex"), "the preamble supports several engines"
        )
    return EngineChoice(("pdflatex",), "no Unicode-engine packages in the preamble")


@dataclass(frozen=True)
class Compiled:
    pdf: Path
    engine: str
    note: str  # how the engine was chosen, and any fallback


def compile_tex(
    tex: Path, timeout: int = 180, engine: str = "auto", search: Sequence[Path] = ()
) -> Compiled:
    """Compile with the declared or detected engine, trying the next candidate on failure."""
    if engine != "auto":
        return Compiled(
            _run(tex, timeout, engine, search), engine, "declared in the template header"
        )
    choice = detect_engine(tex.read_text(encoding="utf-8", errors="replace"), search)
    first_error: CVForgeError | None = None
    for candidate in choice.engines:
        try:
            pdf = _run(tex, timeout, candidate, search)
        except CVForgeError as exc:
            first_error = first_error or exc
            continue
        note = choice.reason
        if candidate != choice.engines[0]:
            note += f"; {choice.engines[0]} failed, so {candidate} was used"
        return Compiled(pdf, candidate, note)
    assert first_error is not None
    tried = ", ".join(choice.engines)
    issue = first_error.issues[0]
    raise CVForgeError(
        [replace(issue, message=f"{issue.message} (engines tried: {tried})")]
    ) from first_error


def compile_pdf(
    tex: Path, timeout: int = 180, engine: str = "auto", search: Sequence[Path] = ()
) -> Path:
    return compile_tex(tex, timeout, engine, search).pdf


def _exec(
    cmd: list[str], cwd: Path, timeout: int, env: dict[str, str], tex: Path
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            # TeX wraps its terminal and log output at a fixed byte width, which can split a
            # multi-byte UTF-8 character; decode leniently so that never crashes a build.
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise CVForgeError(
            [
                Issue(
                    file=str(tex),
                    item=cmd[0],
                    message=f"{cmd[0]} did not finish within {timeout}s.",
                    fix=f"run `{' '.join(cmd)}` in {cwd} by hand to see where it stops.",
                )
            ]
        ) from exc


def _digest(path: Path) -> bytes:
    return hashlib.sha256(path.read_bytes()).digest() if path.exists() else b""


def _run(tex: Path, timeout: int, engine: str, search: Sequence[Path]) -> Path:
    """latexmk when it is on PATH; otherwise the engine itself, two passes, a third if the
    .aux file changed between them (enough for a CV: references and hyperref anchors)."""
    tex = tex.resolve()
    env = search_env(search)
    flags = ["-interaction=nonstopmode", "-halt-on-error", "-file-line-error"]
    if latexmk_available():
        cmd = ["latexmk", ENGINES[engine], *flags, f"-outdir={tex.parent}", tex.name]
        proc = _exec(cmd, tex.parent, timeout, env, tex)
    else:
        if shutil.which(engine) is None:
            raise CVForgeError(
                [
                    Issue(
                        file=str(tex),
                        item=engine,
                        message=f"{engine} is not on PATH, so the PDF cannot be built.",
                        fix="install TeX Live or MiKTeX; run `cvforge doctor` for the exact "
                        "command on this system.",
                    )
                ]
            )
        cmd = [engine, *flags, f"-output-directory={tex.parent}", tex.name]
        aux = tex.with_suffix(".aux")
        previous = b""
        for pass_no in (1, 2, 3):
            proc = _exec(cmd, tex.parent, timeout, env, tex)
            if proc.returncode != 0:
                break
            current = _digest(aux)
            if pass_no >= 2 and current == previous:
                break
            previous = current
    pdf = tex.with_suffix(".pdf")
    if proc.returncode != 0 or not pdf.exists():
        log = tex.with_suffix(".log")
        text = (
            log.read_text(encoding="utf-8", errors="replace")
            if log.exists()
            else proc.stdout + proc.stderr
        )
        line, message = parse_log_error(text)
        raise CVForgeError(
            [
                Issue(
                    file=str(tex),
                    line=line,
                    message=f"LaTeX error: {message}",
                    fix=f"see {log.name}; if the line holds profile text, check its escaping, "
                    "otherwise fix the template at that line.",
                )
            ]
        )
    return pdf


TEX_LOG_WIDTH = 79  # TeX's default max_print_line


def unwrap_log(log: str) -> str:
    """Join log lines TeX broke at max_print_line (MiKTeX ignores the env override)."""
    out: list[str] = []
    carry = ""
    for line in log.replace("\r\n", "\n").split("\n"):
        carry += line
        if len(line) == TEX_LOG_WIDTH:
            continue
        out.append(carry)
        carry = ""
    if carry:
        out.append(carry)
    return "\n".join(out)


def parse_log_error(log: str) -> tuple[int | None, str]:
    log = unwrap_log(log)
    m = re.search(r"^[^\n]*?\.tex:(\d+): (.+)$", log, flags=re.MULTILINE)
    if m:
        return int(m.group(1)), m.group(2).strip()
    m = re.search(r"^! (.+)$", log, flags=re.MULTILINE)
    line = re.search(r"^l\.(\d+)", log, flags=re.MULTILINE)
    if m:
        return (int(line.group(1)) if line else None), m.group(1).strip()
    return None, "the LaTeX run failed; no error line found in the log."
