"""LLM features, end to end, against canned provider responses (no network, no key)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cvforge import cli
from cvforge.config import Config, LLMConfig
from cvforge.errors import CVForgeError
from cvforge.llm import ENV_KEY, client_from_config, json_answer, settings

from .conftest import EXAMPLES, FIXTURES, TEMPLATES

CANNED = FIXTURES / "llm"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "CVFORGE_LLM_PROVIDER",
        "CVFORGE_LLM_MODEL",
        "CVFORGE_LLM_API_KEY",
        "CVFORGE_LLM_CANNED",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def _canned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CVFORGE_LLM_PROVIDER", "canned")
    monkeypatch.setenv("CVFORGE_LLM_CANNED", str(CANNED / name))


def _run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = cli.main(argv)
    return code, capsys.readouterr().out


# ------------------------------------------------------------------ 3a: tailor --rewrite


def test_tailor_rewrite_offers_the_clean_rewrite_and_rejects_new_facts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _canned(monkeypatch, tmp_path, "rewrite.json")
    code, out = _run(
        [
            "tailor",
            "--job", str(EXAMPLES / "job.txt"),
            "-p", str(EXAMPLES / "profile.cv.txt"),
            "-t", str(TEMPLATES / "minimal.tex"),
            "--hat", str(EXAMPLES / "hats" / "developer.toml"),
            "-o", "out/cv.tex",
            "--rewrite", "--yes", "--json",
        ],
        capsys,
    )  # fmt: skip
    assert code == 0, out
    rewrites = {r["original"]: r for r in json.loads(out)["rewrites"]}
    good = rewrites["Shipped a REST API in Node.js and PostgreSQL serving 1M requests a day."]
    number = rewrites[
        "Built a React and TypeScript dashboard used by 30 field staff for daily reporting."
    ]
    tool = rewrites["Added GitHub Actions pipelines running tests on every pull request."]
    assert good["status"] == "accepted" and good["new_facts"] == []
    assert number["status"] == "auto-rejected" and number["new_facts"] == ["45"]
    assert tool["status"] == "auto-rejected" and tool["new_facts"] == ["Jenkins"]
    tex = (tmp_path / "out" / "cv.tex").read_text()
    assert "Delivered a Node.js and PostgreSQL REST API" in tex
    assert "45 field staff" not in tex and "Jenkins" not in tex


# ------------------------------------------------------------------ 3b: one place for settings


def test_settings_read_toml_then_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = Config(llm=LLMConfig(provider="openai", model="gpt-x", api_key_env="MY_KEY"))
    s = settings(cfg)
    assert (s.provider, s.model, s.litellm_model, s.key_source) == (
        "openai",
        "gpt-x",
        "openai/gpt-x",
        "",
    )
    monkeypatch.setenv("MY_KEY", "k1")
    assert settings(cfg).key_source == "MY_KEY"
    monkeypatch.setenv(ENV_KEY, "k2")
    monkeypatch.setenv("CVFORGE_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("CVFORGE_LLM_MODEL", "claude-x")
    s = settings(cfg)
    assert (s.provider, s.litellm_model, s.key_source) == (
        "anthropic",
        "anthropic/claude-x",
        ENV_KEY,
    )


def test_description_never_contains_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_KEY, "sk-very-secret-value")
    s = settings(Config(llm=LLMConfig(provider="anthropic", model="claude-x")))
    assert "key present in CVFORGE_LLM_API_KEY" in s.describe()
    assert "sk-very-secret-value" not in s.describe()


def test_no_model_means_every_llm_feature_is_off() -> None:
    assert "LLM features are off" in settings(Config()).describe()
    with pytest.raises(CVForgeError) as exc:
        client_from_config(Config(), "tag --llm")
    assert "tag --llm is unavailable" in exc.value.issues[0].message
    assert "everything else works without it" in exc.value.issues[0].fix


def test_missing_key_is_named_without_guessing() -> None:
    with pytest.raises(CVForgeError) as exc:
        client_from_config(Config(llm=LLMConfig(provider="openai", model="gpt-x")), "--rewrite")
    assert "needs an API key" in exc.value.issues[0].message
    assert ENV_KEY in exc.value.issues[0].fix


def test_doctor_reports_llm_without_printing_the_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CVFORGE_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("CVFORGE_LLM_MODEL", "claude-x")
    monkeypatch.setenv(ENV_KEY, "sk-very-secret-value")
    _, out = _run(["doctor"], capsys)
    line = next(ln for ln in out.splitlines() if "llm" in ln)
    assert "key present in CVFORGE_LLM_API_KEY" in line
    assert "sk-very-secret-value" not in out


def test_json_answer_tolerates_fences_and_prose() -> None:
    assert json_answer('Sure:\n```json\n{"a": [1]}\n```') == {"a": [1]}
    assert json_answer('{"a": 1} trailing') == {"a": 1}
    assert json_answer("no json here") is None


# ------------------------------------------------------------------ 3c: tag --llm


def test_tag_llm_adds_only_declared_ids_and_writes_only_when_approved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _canned(monkeypatch, tmp_path, "tag.json")
    profile = tmp_path / "profile.cv.txt"
    original = (EXAMPLES / "profile.cv.txt").read_text(encoding="utf-8")
    profile.write_text(original, encoding="utf-8")
    code, out = _run(["tag", "--llm", "-p", str(profile), "--json"], capsys)
    assert code == 0, out
    data = json.loads(out)
    assert data["written"] is False and profile.read_text(encoding="utf-8") == original
    by_id = {p["id"]: p for p in data["proposals"]}
    assert by_id["exp-02.b3"]["added"] == ["ci"]
    assert by_id["exp-02.b3"]["rejected"] == [
        {"skill": "kubernetes", "reason": "not a declared skill id in this profile"}
    ]
    assert by_id["exp-02.b4"]["added"] == []  # already tagged ci: nothing to add
    assert "+        skills: [docker, ci]" in data["diff"]
    code, out = _run(["tag", "--llm", "-p", str(profile), "--json", "--yes"], capsys)
    assert json.loads(out)["written"] is True
    text = profile.read_text(encoding="utf-8")
    assert "skills: [docker, ci]" in text and "kubernetes" not in text


def test_tag_without_llm_flag_says_how(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(["tag", "--json"], capsys)
    assert code != 0 and "tag needs --llm" in out


# ------------------------------------------------------------------ 3d: check --llm-reader


@pytest.mark.tex
def test_llm_reader_is_an_advisory_column_and_never_gates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _canned(monkeypatch, tmp_path, "reader.json")
    args = ["-p", str(EXAMPLES / "profile.cv.txt"), "-t", str(TEMPLATES / "minimal.tex")]
    hat = ["--hat", str(EXAMPLES / "hats" / "developer.toml")]
    code, _ = _run(["build", *args, *hat, "-o", "out/cv.tex", "--compile"], capsys)
    assert code == 0
    code, out = _run(
        ["check", "out/cv.tex", "--job", str(EXAMPLES / "job.txt"), "--llm-reader", "--json"],
        capsys,
    )
    data = json.loads(out)
    reader = data["llm_reader"]
    assert reader["gate"] is False and reader["facts_found"] < reader["facts_checked"]
    assert reader["evidenced_skills"] == ["Python"]
    assert reader["rejected_skills"] == ["Kubernetes"]
    assert "llm-reader" not in data["gates"]
    assert code == 0  # the gating readers passed; the model's misses do not fail the check
