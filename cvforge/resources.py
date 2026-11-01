"""Files shipped with the package: built-in templates and the fictional example profile.

In a wheel they live under cvforge/ (see [tool.hatch.build.targets.wheel.force-include]);
in a source checkout they are read from the repository's templates/ and examples/ folders.
"""

from __future__ import annotations

from pathlib import Path

_PKG = Path(__file__).resolve().parent
_BASES = (_PKG, _PKG.parent)


def data_path(*parts: str) -> Path | None:
    for base in _BASES:
        path = base.joinpath(*parts)
        if path.exists():
            return path
    return None


def builtin_template(name: str) -> Path | None:
    """`minimal` -> the shipped templates/minimal.tex, if it exists."""
    if "/" in name or "\\" in name or name.endswith(".tex"):
        return None
    return data_path("templates", f"{name}.tex")


def builtin_templates() -> list[str]:
    folder = data_path("templates")
    return sorted(p.stem for p in folder.glob("*.tex")) if folder else []
