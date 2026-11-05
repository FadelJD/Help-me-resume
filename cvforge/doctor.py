"""cvforge doctor: is everything this system needs installed, and how to install what is not.

One line per item. Required items are a TeX engine and every reader that gates on this OS
(parsers.DEFAULT_GATES); everything else is optional and never changes the exit code.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from cvforge.config import Config, load_config
from cvforge.errors import CVForgeError
from cvforge.llm import settings
from cvforge.parsers import default_gates
from cvforge.platforms import OS, current_os, install_command, os_label
from cvforge.score import SEMANTIC_MODEL

ENGINES = ("pdflatex", "xelatex", "lualatex")
# reader name -> (what provides it, "bin" for a program on PATH or "py" for a Python module)
READERS: dict[str, tuple[str, str]] = {
    "pdftotext": ("pdftotext", "bin"),
    "pdfplumber": ("pdfplumber", "py"),
    "pypdf-layout": ("pypdf", "py"),
    "pdfium": ("pypdfium2", "py"),
    "pdfminer": ("pdfminer", "py"),
}


@dataclass(frozen=True)
class Item:
    name: str
    ok: bool
    detail: str
    required: bool
    fix: str = ""
    info: bool = False  # a fact about the system, not something to install

    @property
    def line(self) -> str:
        state = "OK" if self.ok else "MISSING"
        if self.info:
            return f"{state:<8}{self.name}: {self.detail}"
        need = "required" if self.required else "optional"
        tail = f" | install: {self.fix}" if not self.ok and self.fix else ""
        return f"{state:<8}{self.name} ({need}): {self.detail}{tail}"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ok": self.ok,
            "required": self.required,
            "detail": self.detail,
            "fix": self.fix,
        }


def _has(provider: str, kind: str) -> bool:
    if kind == "bin":
        return shutil.which(provider) is not None
    return importlib.util.find_spec(provider) is not None


def _model_cached() -> bool:
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    folder = hub / ("models--" + SEMANTIC_MODEL.replace("/", "--"))
    return folder.is_dir()


def diagnose(os_name: OS | None = None) -> list[Item]:
    os_name = os_name or current_os()
    gates = default_gates(os_name)
    items = [Item("system", True, os_label(os_name), False, info=True)]
    py_ok = sys.version_info >= (3, 11)
    items.append(
        Item(
            "python",
            py_ok,
            f"{sys.version.split()[0]} (3.11 or newer needed)",
            True,
            install_command("python", os_name),
        )
    )
    engines = [e for e in ENGINES if shutil.which(e)]
    items.append(
        Item(
            "tex engine",
            bool(engines),
            ", ".join(engines) if engines else "no pdflatex, xelatex or lualatex on PATH",
            True,
            install_command("tex", os_name),
        )
    )
    items.append(
        Item(
            "latexmk",
            shutil.which("latexmk") is not None,
            "found" if shutil.which("latexmk") else "not found; cvforge runs the engine itself",
            False,
            install_command("latexmk", os_name),
        )
    )
    for reader, (provider, kind) in READERS.items():
        gate = reader in gates
        ok = _has(provider, kind)
        role = "gating reader on this system" if gate else "advisory reader"
        items.append(
            Item(
                f"reader {reader}",
                ok,
                f"{role}; {'found' if ok else 'not installed'}",
                gate,
                install_command(provider if kind == "py" else "pdftotext", os_name),
            )
        )
    has_lib = importlib.util.find_spec("sentence_transformers") is not None
    cached = has_lib and _model_cached()
    detail = (
        "library and model found"
        if cached
        else "library found, model not downloaded"
        if has_lib
        else "not installed"
    )
    items.append(
        Item(
            "semantic score",
            cached,
            f"{detail}; used by check --job for the similarity score",
            False,
            install_command("semantic", os_name),
        )
    )
    items.append(_llm_item())
    return items


def _llm_item() -> Item:
    """Whether an LLM is configured and a key is present; the key itself is never shown."""
    try:
        s = settings(load_config())
    except CVForgeError:
        s = settings(Config())
    detail = s.describe()
    ok = s.configured and (s.key_source != "" or not s.needs_key)
    if ok and s.provider != "canned" and importlib.util.find_spec("litellm") is None:
        ok, detail = False, detail + "; LiteLLM is not installed"
    fix = (
        "set [llm] provider and model in cvforge.toml, export CVFORGE_LLM_API_KEY, and "
        'pip install "cvforge[llm]"; only tailor --rewrite, tag --llm and check --llm-reader '
        "use it"
    )
    return Item("llm", ok, detail, False, fix)


def missing_required(os_name: OS | None = None) -> list[str]:
    return [i.name for i in diagnose(os_name) if i.required and not i.ok]
