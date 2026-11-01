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
    # A bullet starting with `[` would become \item's optional argument ("File ended while
    # scanning use of \@item", found by the escaper fuzz); braces make brackets plain text.
    "[": "{[}",
    "]": "{]}",
}
_WS = re.compile(r"\s+")
# Characters with no business in a CV that would break LaTeX or hide text.
_CONTROL = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff]"
)


# Long unbroken tokens (URLs, paths, identifiers) cannot wrap and run off the right margin, where
# text is cut from the PDF (found by the escaper fuzz). For free text (bullets), inside a token
# longer than LONG_TOKEN, allow a line break after URL punctuation, and after every LONG_TOKEN
# characters without one. Not for fields templates may reuse in links (email, link text).
LONG_TOKEN = 24
# A break with its own stretch, cancelled when not taken. A bare \allowbreak inside a token has
# no glue around it, so TeX finds every line infeasible and still overflows (escaper fuzz).
BREAK = r"\hspace{0pt plus 1fil}\penalty0\hspace{0pt plus -1fil}"
_BREAK_AFTER = frozenset("/._-?&=#@:,;")


def _escape_token(token: str, breakable: bool) -> str:
    if not breakable or len(token) <= LONG_TOKEN:
        return "".join(_SPECIAL.get(ch, ch) for ch in token)
    out: list[str] = []
    run = 0
    for i, ch in enumerate(token):
        out.append(_SPECIAL.get(ch, ch))
        run += 1
        last = i == len(token) - 1
        if not last and (ch in _BREAK_AFTER or run >= LONG_TOKEN):
            out.append(BREAK)
            run = 0
    return "".join(out)


def escape(text: str, *, breakable: bool = False) -> str:
    """Escape user text for LaTeX body text; `breakable` adds line-break points to long tokens."""
    text = _CONTROL.sub("", text)
    text = _WS.sub(" ", text).strip()
    return " ".join(_escape_token(token, breakable) for token in text.split(" "))


def escape_url(url: str) -> str:
    """Escape a URL for the first argument of hyperref's \\href."""
    url = _WS.sub("", _CONTROL.sub("", url))
    url = url.replace("\\", "/").replace("{", "%7B").replace("}", "%7D")
    return url.replace("%", r"\%").replace("#", r"\#")
