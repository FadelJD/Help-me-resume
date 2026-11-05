from __future__ import annotations

import types
from pathlib import Path

import pytest

from cvforge import pipeline
from cvforge.config import Config, LLMConfig
from cvforge.errors import CVForgeError
from cvforge.llm import LiteLLMClient, Settings
from cvforge.parse import load_profile
from cvforge.rewrite import (
    CannedRewriter,
    Proposal,
    find_new_facts,
    profile_vocabulary,
)
from cvforge.template import ids_in_tex

from .conftest import EXAMPLES, FIXTURES, TEMPLATES

PROFILE = load_profile(EXAMPLES / "profile.cv.txt").profile
VOCAB = profile_vocabulary(PROFILE)
SRC = "Shipped a REST API in Node.js and PostgreSQL serving 1M requests a day."
SRC_WITH_SKILLS = SRC + " Node.js PostgreSQL REST APIs"


@pytest.mark.parametrize(
    ("rewrite", "added"),
    [
        ("Delivered a REST API on Node.js and PostgreSQL handling 2M daily requests.", "2m"),
        ("Shipped a REST API in Node.js, PostgreSQL and Redis serving 1M requests a day.", "Redis"),
        ("Shipped a REST API with docker serving 1M requests a day.", "docker"),
        ("Shipped a REST API at Google serving 1M requests a day.", "Google"),
        ("Shipped a REST API serving 1M requests a day since March.", "March"),
        ("Shipped a REST API serving 1M requests a day for three teams.", "three"),
        ("Shipped a REST API serving 1M requests a day, cutting costs 30%.", "30%"),
        ("Shipped a gRPC API serving 1M requests a day.", "gRPC"),
        ("Architected a REST API serving 1M requests a day.", "Architected"),
    ],
)
def test_rewrite_adding_a_fact_is_rejected(rewrite: str, added: str) -> None:
    assert added in find_new_facts(SRC_WITH_SKILLS, rewrite, VOCAB)


@pytest.mark.parametrize(
    "rewrite",
    [
        "Delivered a REST API on Node.js and PostgreSQL handling 1M daily requests.",
        "Built and shipped a PostgreSQL-backed REST API in Node.js serving 1M requests a day.",
        "Shipped a REST API serving 1M requests a day.",  # dropping facts is allowed
    ],
)
def test_faithful_rewrite_passes(rewrite: str) -> None:
    assert find_new_facts(SRC_WITH_SKILLS, rewrite, VOCAB) == []


def test_tool_from_elsewhere_in_profile_is_rejected() -> None:
    # Python is a declared skill, but not of this bullet: moving it here adds a claim.
    assert "Python" in find_new_facts(SRC_WITH_SKILLS, SRC.replace("Node.js", "Python"), VOCAB)


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _tailor(out: Path, answers: dict[str, str], decide: str = "a") -> tuple[object, list[Proposal]]:
    def approve(proposals: list[Proposal]) -> None:
        for p in proposals:
            if p.valid:
                p.status = "accepted" if decide == "a" else "rejected"

    return pipeline.tailor(
        profile=EXAMPLES / "profile.cv.txt",
        template=TEMPLATES / "minimal.tex",
        hat=str(EXAMPLES / "hats" / "developer.toml"),
        job=str(FIXTURES / "job_backend.txt"),
        output=out,
        max_bullets=None,
        compile_pdf_too=False,
        rewrite=True,
        approve=approve,
        rewriter=CannedRewriter(answers),
    )


GOOD = "Delivered a REST API on Node.js and PostgreSQL handling 1M daily requests."
BAD = "Built a Python pipeline migrating 4,000 knowledge-base articles to DocFX on Kubernetes."
ORIG_BAD = "Built a Python pipeline migrating 400 knowledge-base articles to DocFX."


def test_tailor_applies_only_approved_faithful_rewrites(workdir: Path) -> None:
    result, proposals = _tailor(workdir / "t.tex", {SRC: GOOD, ORIG_BAD: BAD})
    by_id = {p.qid: p for p in proposals}
    assert by_id["exp-02.b1"].status == "accepted"
    assert by_id["exp-01.b2"].status == "auto-rejected"
    assert set(by_id["exp-01.b2"].new_facts) >= {"4000", "Kubernetes"}
    tex = result.tex.read_text()  # type: ignore[attr-defined]
    assert "handling 1M daily requests. % id:exp-02.b1" in tex
    assert "migrating 400 knowledge-base" in tex and "4,000" not in tex
    assert "exp-02.b1" in ids_in_tex(tex)
    rewrites = result.report["rewrites"]  # type: ignore[attr-defined]
    assert {r["id"]: r["status"] for r in rewrites}["exp-02.b1"] == "accepted"


def test_tailor_rejected_rewrite_keeps_original(workdir: Path) -> None:
    result, _ = _tailor(workdir / "r.tex", {SRC: GOOD}, decide="r")
    assert SRC.replace("1M", "1M") in result.tex.read_text()  # type: ignore[attr-defined]


def test_rewrite_unavailable_without_llm_config() -> None:
    with pytest.raises(CVForgeError) as exc:
        pipeline.rewriter_from_config(Config())
    assert "unavailable" in exc.value.issues[0].message
    assert "everything else works" in exc.value.issues[0].fix


def test_litellm_missing_says_how_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    def fail(name: str) -> object:
        raise ImportError(name)

    monkeypatch.setattr(importlib, "import_module", fail)
    with pytest.raises(CVForgeError) as exc:
        LiteLLMClient(Settings("ollama", "llama3", "", ""))
    assert "cvforge[llm]" in exc.value.issues[0].fix


def test_litellm_rewriter_calls_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    seen: dict[str, object] = {}

    def completion(**kwargs: object) -> object:
        seen.update(kwargs)
        message = types.SimpleNamespace(content=' "Delivered it." ')
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    monkeypatch.setattr(
        importlib, "import_module", lambda name: types.SimpleNamespace(completion=completion)
    )
    monkeypatch.setenv("MY_KEY", "secret")
    cfg = Config(llm=LLMConfig(model="anthropic/some-model", api_key_env="MY_KEY"))
    engine = pipeline.rewriter_from_config(cfg)
    assert engine.rewrite("Did it.", job="ad", title_line="Dev") == "Delivered it."
    assert seen["model"] == "anthropic/some-model" and seen["api_key"] == "secret"
    assert seen["temperature"] == 0


@pytest.mark.tex
def test_check_passes_on_rewritten_cv(workdir: Path) -> None:
    from cvforge.check import check
    from cvforge.config import Thresholds

    result, _ = _tailor(workdir / "c.tex", {SRC: GOOD})
    report = check(result.tex, None, Thresholds(), semantic=False)  # type: ignore[attr-defined]
    assert report.roundtrip_ok, [(p.name, p.misses) for p in report.parsers]
