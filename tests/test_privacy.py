"""Privacy guard: personal CV material stays out of git.

private/ is ignored. private/blocklist.txt (itself private) lists strings that must never appear
in a tracked file: the user's name, email, phone, employers. This test runs in the normal suite
and in the pre-commit hook (scripts/hooks/pre-commit); in a checkout without the blocklist, such
as CI, only the ignore rules can be checked.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOCKLIST = ROOT / "private" / "blocklist.txt"


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode()
    return [ROOT / p for p in out.split("\0") if p]


def blocked_strings() -> list[str]:
    if not BLOCKLIST.exists():
        return []
    lines = BLOCKLIST.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def find_leaks(files: list[Path], blocked: list[str]) -> list[str]:
    needles = [b.casefold() for b in blocked]
    leaks = []
    for path in files:
        if not path.is_file():
            continue
        text = path.read_bytes().decode("utf-8", errors="ignore").casefold()
        for needle in needles:
            if needle in text:
                leaks.append(f"{path.relative_to(ROOT)} contains a blocklisted string")
                break
    return leaks


def test_private_folder_is_ignored() -> None:
    for rel in ("private/", "private/profile.cv.txt", "private/out/cv.pdf", "private/cv-a.pdf"):
        res = subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT)
        assert res.returncode == 0, f"{rel} is not ignored by .gitignore"


def test_no_private_file_is_tracked() -> None:
    assert not [p for p in tracked_files() if "private" in p.relative_to(ROOT).parts[:1]]


def test_no_tracked_file_contains_a_blocklisted_string() -> None:
    blocked = blocked_strings()
    # Without private/blocklist.txt (e.g. in CI) there is nothing to compare against.
    leaks = find_leaks(tracked_files(), blocked) if blocked else []
    # The message never repeats the blocklisted string itself.
    assert not leaks, "\n".join(leaks)
