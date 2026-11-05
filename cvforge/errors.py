"""Structured problems. Every error names the file, the line or item id, and the fix."""

from __future__ import annotations

from dataclasses import dataclass, field

from cvforge.platforms import show_path


@dataclass(frozen=True)
class Issue:
    file: str
    message: str
    fix: str
    line: int | None = None
    item: str | None = None
    severity: str = "error"  # "error" | "warning"

    def __post_init__(self) -> None:
        object.__setattr__(self, "file", show_path(self.file))

    def __str__(self) -> str:
        where = self.file if self.line is None else f"{self.file}:{self.line}"
        item = f" [{self.item}]" if self.item else ""
        return f"{where}{item}: {self.severity}: {self.message} Fix: {self.fix}"

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "line": self.line,
            "item": self.item,
            "severity": self.severity,
            "message": self.message,
            "fix": self.fix,
        }


@dataclass
class CVForgeError(Exception):
    """Raised with one or more issues; the CLI prints each one and exits non-zero."""

    issues: list[Issue] = field(default_factory=list)

    def __str__(self) -> str:
        return "\n".join(str(i) for i in self.issues)


def errors_only(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]
