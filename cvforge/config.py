"""cvforge.toml: project defaults. Every value has a default, so the file is optional."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from cvforge.errors import CVForgeError, Issue

LocaleName = Literal["au", "uk", "us", "th"]


@dataclass(frozen=True)
class Locale:
    name: str
    cv_word: str
    paper: str
    present: str
    date_format: str  # strftime format applied to the first day of the month


LOCALES: dict[str, Locale] = {
    "th": Locale("th", "CV", "a4paper", "Present", "%b %Y"),
    "uk": Locale("uk", "CV", "a4paper", "Present", "%b %Y"),
    "au": Locale("au", "Résumé", "a4paper", "Present", "%b %Y"),
    "us": Locale("us", "Résumé", "letterpaper", "Present", "%b %Y"),
}


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keyword: float = Field(default=0.5, ge=0, le=1)
    semantic: float = Field(default=0.5, ge=0, le=1)
    evidence: float = Field(default=1.0, ge=0, le=1)


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # LiteLLM model string, e.g. "ollama/llama3"; empty means rewrite is off.
    model: str = ""
    # Optional env var holding the API key; LiteLLM's own defaults apply otherwise.
    api_key_env: str = ""


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: str = "profile.cv.txt"
    template: str = ""
    hat: str = ""
    hats_dir: str = "hats"
    locale: LocaleName = "th"
    out_dir: str = "out"
    thresholds: Thresholds = Thresholds()
    llm: LLMConfig = LLMConfig()


DEFAULT_CONFIG_TEXT = """\
# cvforge.toml - project defaults. Command-line flags override these.
profile = "profile.cv.txt"
template = "{template}"
hat = "{hat}"
hats_dir = "hats"
locale = "{locale}"          # au | uk | us | th : date style, CV/Résumé wording, page size
out_dir = "out"

[thresholds]                 # reported by `check`; only enforced with `check --strict`
keyword = 0.5
semantic = 0.5
evidence = 1.0

[llm]                        # optional, only for `tailor --rewrite` (pip install cvforge[llm])
model = ""                   # LiteLLM model string, e.g. "ollama/llama3"; empty = rewrite off
api_key_env = ""
"""


def load_config(path: Path = Path("cvforge.toml")) -> Config:
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return Config.model_validate(data)
    except tomllib.TOMLDecodeError as exc:
        raise CVForgeError(
            [Issue(file=str(path), message=f"invalid TOML: {exc}.", fix="fix the TOML syntax.")]
        ) from exc
    except ValidationError as exc:
        raise CVForgeError(
            [
                Issue(
                    file=str(path),
                    message=f"`{'.'.join(map(str, e['loc']))}`: {e['msg']}.",
                    fix="see the comments in a fresh `cvforge init` config for valid values.",
                )
                for e in exc.errors()
            ]
        ) from exc
