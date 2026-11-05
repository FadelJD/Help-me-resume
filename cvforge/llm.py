"""The one place cvforge talks to a language model.

Settings live in cvforge.toml under [llm] and can be overridden by environment variables:

    [llm]
    provider = "anthropic"          # CVFORGE_LLM_PROVIDER   (LiteLLM provider name, or "canned")
    model = "claude-sonnet-5-5"     # CVFORGE_LLM_MODEL
    api_key_env = "ANTHROPIC_API_KEY"  # where to read the key; CVFORGE_LLM_API_KEY always wins

The key is only ever read from the environment, never from cvforge.toml, and never printed.
Every LLM feature (tailor --rewrite, tag --llm, check --llm-reader) gets its client from
`client_from_config`. Without a configured model none of them run; nothing else needs one.

The "canned" provider answers from a JSON file of prepared responses (`canned = "file.json"`
or CVFORGE_LLM_CANNED): a list of {"match": text, "response": text}; the first entry whose
`match` occurs in the prompt answers it. Tests and dry runs use it; it never touches a network.
"""

from __future__ import annotations

import importlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from cvforge.config import Config
from cvforge.errors import CVForgeError, Issue

ENV_PROVIDER = "CVFORGE_LLM_PROVIDER"
ENV_MODEL = "CVFORGE_LLM_MODEL"
ENV_KEY = "CVFORGE_LLM_API_KEY"
ENV_CANNED = "CVFORGE_LLM_CANNED"

# LiteLLM's own default key variables, so a key already exported for a provider is found.
PROVIDER_KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}
NO_KEY_PROVIDERS = {"ollama", "canned"}  # local models and canned answers need no key


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    key_source: str  # the environment variable the key comes from; empty when none is set
    canned: str

    @property
    def configured(self) -> bool:
        return bool(self.model) or self.provider == "canned"

    @property
    def needs_key(self) -> bool:
        return self.provider not in NO_KEY_PROVIDERS

    @property
    def litellm_model(self) -> str:
        if not self.provider or "/" in self.model:
            return self.model
        return f"{self.provider}/{self.model}"

    def describe(self) -> str:
        """For doctor: what is configured and whether a key is present, never the key."""
        if not self.configured:
            return "not configured; LLM features are off and everything else works without them"
        what = f"provider {self.provider or 'from model name'}, model {self.model or '-'}"
        if self.provider == "canned":
            return f"canned responses from {self.canned or '(no file set)'}"
        if not self.needs_key:
            return f"{what}; no key needed"
        if self.key_source:
            return f"{what}; key present in {self.key_source}"
        return f"{what}; no key found"


def settings(cfg: Config) -> Settings:
    provider = os.environ.get(ENV_PROVIDER) or cfg.llm.provider
    model = os.environ.get(ENV_MODEL) or cfg.llm.model
    if not provider and "/" in model:
        provider = model.split("/", 1)[0]
    candidates = [ENV_KEY, cfg.llm.api_key_env, PROVIDER_KEYS.get(provider, "")]
    key_source = next((name for name in candidates if name and os.environ.get(name)), "")
    canned = os.environ.get(ENV_CANNED) or cfg.llm.canned
    return Settings(provider, model, key_source, canned)


class Client(Protocol):
    def complete(self, system: str, user: str) -> str: ...


@dataclass
class CannedClient:
    responses: list[tuple[str, str]]  # (text the prompt must contain, answer)
    prompts: list[str] = field(default_factory=list)  # every prompt seen, for tests

    @classmethod
    def from_file(cls, path: Path) -> CannedClient:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            pairs = [(str(d["match"]), str(d["response"])) for d in data]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CVForgeError(
                [
                    Issue(
                        file=str(path),
                        item="llm.canned",
                        message=f"cannot read canned responses: {exc}.",
                        fix='write a JSON list of {"match": "...", "response": "..."} objects.',
                    )
                ]
            ) from exc
        return cls(pairs)

    def complete(self, system: str, user: str) -> str:
        self.prompts.append(user)
        return next((answer for match, answer in self.responses if match in user), "")


@dataclass
class LiteLLMClient:
    settings: Settings
    _completion: Callable[..., Any] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        try:
            module = importlib.import_module("litellm")
        except ImportError as exc:
            raise CVForgeError(
                [
                    Issue(
                        file="cvforge.toml",
                        item="llm",
                        message="LLM features need LiteLLM, which is not installed.",
                        fix='pip install "cvforge[llm]" (with pipx: pipx inject cvforge litellm).',
                    )
                ]
            ) from exc
        self._completion = module.completion

    def complete(self, system: str, user: str) -> str:
        assert self._completion is not None
        kwargs: dict[str, Any] = {}
        if self.settings.key_source:
            kwargs["api_key"] = os.environ[self.settings.key_source]
        resp = self._completion(
            model=self.settings.litellm_model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
            **kwargs,
        )
        return str(resp.choices[0].message.content or "")


def client_from_config(cfg: Config, feature: str) -> Client:
    """The client for an LLM feature, or an error saying how to configure one."""
    s = settings(cfg)
    if not s.configured:
        raise CVForgeError(
            [
                Issue(
                    file="cvforge.toml",
                    item="llm.model",
                    message=f"{feature} is unavailable: no LLM is configured.",
                    fix="set [llm] provider and model in cvforge.toml (or CVFORGE_LLM_PROVIDER and "
                    "CVFORGE_LLM_MODEL), put the key in CVFORGE_LLM_API_KEY, and install "
                    '"cvforge[llm]"; everything else works without it.',
                )
            ]
        )
    if s.provider == "canned":
        if not s.canned:
            raise CVForgeError(
                [
                    Issue(
                        file="cvforge.toml",
                        item="llm.canned",
                        message="provider is canned but no responses file is set.",
                        fix='set [llm] canned = "responses.json" or CVFORGE_LLM_CANNED.',
                    )
                ]
            )
        return CannedClient.from_file(Path(s.canned))
    if s.needs_key and not s.key_source:
        raise CVForgeError(
            [
                Issue(
                    file="cvforge.toml",
                    item="llm",
                    message=f"{feature} needs an API key for {s.provider or s.model}; none is set.",
                    fix=f"export {ENV_KEY}=<your key> (it is read from the environment only).",
                )
            ]
        )
    return LiteLLMClient(s)


def json_answer(text: str) -> Any:
    """The JSON object in a model answer, tolerating a ```json fence or text around it."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = fenced.group(1) if fenced else text
    start = body.find("{")
    end = body.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        return json.loads(body[start : end + 1])
    except ValueError:
        return None
