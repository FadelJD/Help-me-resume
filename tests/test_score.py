from __future__ import annotations

from cvforge.score import BM25, keyword_coverage, relevance, semantic_similarity, tokenize


def test_tokenize_keeps_tech_terms() -> None:
    tokens = tokenize("Built REST APIs in Node.js, C# and .NET for the team.")
    assert {"rest", "api", "node.js", "c#", ".net", "built"} <= set(tokens)
    assert "the" not in tokens and "team" not in tokens


def test_tokenize_plurals_match_singular() -> None:
    assert tokenize("services") == tokenize("service")


def test_bm25_prefers_matching_doc() -> None:
    docs = [tokenize("PostgreSQL REST API"), tokenize("LaTeX typesetting")]
    bm = BM25(docs)
    q = tokenize("REST API with PostgreSQL")
    assert bm.score(q, 0) > bm.score(q, 1) == 0


def test_relevance_is_scaled() -> None:
    rel = relevance(["docker compose", "react dashboard", "docker"], "docker")
    assert max(rel) == 1.0 and rel[1] == 0.0


def test_relevance_no_overlap_is_zero() -> None:
    assert relevance(["alpha"], "omega") == [0.0]


def test_keyword_coverage() -> None:
    score, missing = keyword_coverage("Node.js PostgreSQL Docker Kubernetes", "Node.js and Docker")
    assert 0 < score < 1
    assert missing == ["kubernete", "postgresql"]
    assert keyword_coverage("Docker", "docker")[0] == 1.0
    assert keyword_coverage("", "anything") == (0.0, [])


def test_semantic_is_optional() -> None:
    value = semantic_similarity("a", "b")
    assert value is None or -1.0 <= value <= 1.0
