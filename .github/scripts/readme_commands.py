"""Turn the README's install block for one OS, plus its Quick start block, into a CI script.

    python readme_commands.py README.md linux   > quickstart.sh
    python readme_commands.py README.md windows > quickstart.ps1

The commands are taken verbatim, in order. Substitutions, and only these:
- the `pipx install ... cvforge` line installs the checkout under test ($REPO) instead of the
  published repository, so the test checks the code being pushed;
- on Windows, `winget install` lines become comments: hosted runners have no winget, so Python
  comes from actions/setup-python and TeX Live from TeX-Live/setup-texlive-action instead.
"""

from __future__ import annotations

import re
import sys

SUBSECTIONS = {"linux": ("Ubuntu or Debian", "bash"), "windows": ("Windows", "powershell")}


def _section(text: str, heading: str, level: str) -> str:
    """The text under `level heading`, up to the next heading of the same or a higher level.
    Lines inside code fences are never headings (a `# comment` in a block is not one)."""
    out: list[str] = []
    inside = fenced = False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        hashes = len(line) - len(line.lstrip("#"))
        is_heading = not fenced and 0 < hashes <= len(level) and line[hashes : hashes + 1] == " "
        if is_heading and inside:
            break
        if is_heading and line == f"{level} {heading}":
            inside = True
            continue
        if inside:
            out.append(line)
    if not inside:
        raise SystemExit(f"README.md has no '{level} {heading}' heading")
    return "\n".join(out) + "\n"


def _blocks(section: str, lang: str) -> list[str]:
    return [
        ln
        for block in re.findall(rf"```{lang}\n(.*?)```", section, re.S)
        for ln in block.strip().splitlines()
    ]


def commands(text: str, os_name: str) -> tuple[list[str], list[str]]:
    """(install lines, quick start lines), checked for the shape the README promises."""
    heading, lang = SUBSECTIONS[os_name]
    install = _blocks(_section(_section(text, "Install", "##"), heading, "###"), lang)
    quick = _blocks(_section(text, "Quick start", "##"), "bash")
    pipx = [ln for ln in install if "pipx install " in ln and "cvforge" in ln]
    assert len(pipx) == 1, f"{heading}: expected one cvforge install line, got {pipx}"
    assert install and install[-1] == "cvforge doctor", f"{heading}: must end with cvforge doctor"
    for needed in ("cvforge init", "cvforge build", "cvforge check"):
        assert any(ln.startswith(needed) for ln in quick), f"Quick start lacks {needed}"
    return install, quick


def script(text: str, os_name: str) -> str:
    install, quick = commands(text, os_name)
    out: list[str] = []
    if os_name == "linux":
        out.append("set -euxo pipefail")
        for ln in install + quick:
            out.append('pipx install "$REPO[check]"' if "pipx install " in ln else ln)
        return "\n".join(out) + "\n"
    out += ["$ErrorActionPreference = 'Stop'", "$PSNativeCommandUseErrorActionPreference = $true"]
    for ln in install + quick:
        if ln.startswith("winget install"):
            out.append(f"# CI: not run (no winget on hosted runners): {ln}")
            continue
        if "pipx install " in ln:
            ln = ln.split("pipx install ", 1)[0] + 'pipx install "$($env:REPO)[check]"'
        if not ln.startswith("#"):
            out.append(f"Write-Host '+ {ln.replace(chr(39), chr(39) * 2)}'")
        out.append(ln)
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as fh:
        sys.stdout.write(script(fh.read(), sys.argv[2]))
