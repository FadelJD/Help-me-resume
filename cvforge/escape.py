"""LaTeX escaping of user text. Applied once, at render time, to every user string.

One pass over the characters, so an escape is never escaped again. Whitespace (including
newlines) collapses to single spaces, so a user string can never start a new line in the
`.tex` and break the `% id:` traceability comment on its line.
"""

from __future__ import annotations

import re

_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "<": r"\textless{}",
    ">": r"\textgreater{}",
    "|": r"\textbar{}",
}
_WS = re.compile(r"\s+")
# Characters with no business in a CV that would break LaTeX or hide text.
_CONTROL = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff]"
)


def escape(text: str) -> str:
    """Escape user text for LaTeX body text."""
    text = _CONTROL.sub("", text)
    text = _WS.sub(" ", text).strip()
    return "".join(_SPECIAL.get(ch, ch) for ch in text)


def escape_url(url: str) -> str:
    """Escape a URL for the first argument of hyperref's \\href."""
    url = _WS.sub("", _CONTROL.sub("", url))
    url = url.replace("\\", "/").replace("{", "%7B").replace("}", "%7D")
    return url.replace("%", r"\%").replace("#", r"\#")
