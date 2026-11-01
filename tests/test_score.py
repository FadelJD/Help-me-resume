from __future__ import annotations

from cvforge.score import BM25, cosine, keyword_coverage, relevance, semantic_similarity, tokenize


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


class _Fake:
    def encode(self, sentences: list[str], normalize_embeddings: bool = True) -> list[list[float]]:
        return [[3.0, 4.0], [4.0, 3.0]]


def test_semantic_with_fake_encoder() -> None:
    assert semantic_similarity("a", "b", _Fake()).score == 0.96


def test_cosine() -> None:
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_semantic_without_library_explains() -> None:
    result = semantic_similarity("a", "b")
    if result.score is None:  # the normal case in CI: no sentence-transformers or no cached model
        assert result.reason and result.fix and "SentenceTransformer(" in result.fix
