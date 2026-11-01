"""Orchestration used by the CLI. Each function is one command, returns a result, prints nothing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cvforge.config import Config, load_config
from cvforge.errors import CVForgeError, Issue, errors_only
from cvforge.parse import ParsedProfile, load_profile
from cvforge.validate import validate_profile


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
