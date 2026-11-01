"""Deterministic text scoring: tokenizer, BM25, keyword coverage, optional local embeddings."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

_STOPWORDS_TEXT = """
a about above after all also an and any are as at be been being but by can could did do does
for from had has have having he her here his how i if in into is it its just me more most my
no not of on once only or other our out over own same she should so some such than that the
their them then there these they this those through to too under until up very was we were
what when where which while who whom why will with would you your yours etc e.g i.e via per
plus including include includes using use used within across able ability strong good great
years year experience experienced role team teams work working join hiring looking seeking
candidate candidates must nice bonus preferred required requirements responsibilities skills
knowledge understanding familiarity proven excellent clear new day daily well
"""
STOPWORDS = frozenset(_STOPWORDS_TEXT.split())
_TOKEN = re.compile(r"\.?[a-z0-9][a-z0-9+#]*(?:\.[a-z0-9+#]+)*")


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    out = []
    for raw in _TOKEN.findall(text.lower()):
        token = raw.rstrip(".")
        if len(token) < 2 or token in STOPWORDS or token.isdigit():
            continue
        out.append(_stem(token))
    return out


class BM25:
    """Okapi BM25 over a small fixed corpus (the profile's bullets)."""

    def __init__(self, docs: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.docs = [Counter(d) for d in docs]
        self.lengths = [len(d) for d in docs]
        self.avg = (sum(self.lengths) / len(docs)) if docs else 0.0
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, query: Sequence[str], index: int) -> float:
        doc, length = self.docs[index], self.lengths[index]
        total = 0.0
        for term, qtf in Counter(query).items():
            tf = doc.get(term, 0)
            if not tf:
                continue
            norm = tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self.avg))
            qweight = qtf * (self.k1 + 1) / (qtf + self.k1)
            total += self.idf[term] * norm * qweight
        return total


def relevance(docs: Sequence[str], query: str) -> list[float]:
    """BM25 of each doc against the query, scaled so the best doc is 1.0 (all 0 if no overlap)."""
    tokens = [tokenize(d) for d in docs]
    if not tokens:
        return []
    bm25 = BM25(tokens)
    q = tokenize(query)
    raw = [bm25.score(q, i) for i in range(len(tokens))]
    top = max(raw, default=0.0)
    return [round(r / top, 4) if top > 0 else 0.0 for r in raw]


def keyword_coverage(
    job: str, cv: str, k1: float = 1.5, top_missing: int = 15
) -> tuple[float, list[str]]:
    """Share of the job ad's terms found in the CV, each term weighted by BM25 tf saturation.

    Returns (score in 0..1, the heaviest job terms absent from the CV).
    """
    job_tf = Counter(tokenize(job))
    if not job_tf:
        return 0.0, []
    cv_terms = set(tokenize(cv))
    weights = {t: tf * (k1 + 1) / (tf + k1) for t, tf in job_tf.items()}
    total = sum(weights.values())
    hit = sum(w for t, w in weights.items() if t in cv_terms)
    missing = sorted((t for t in weights if t not in cv_terms), key=lambda t: (-weights[t], t))
    return round(hit / total, 4), missing[:top_missing]


def semantic_similarity(
    a: str, b: str, model: str = "sentence-transformers/all-MiniLM-L6-v2"
) -> float | None:
    """Cosine similarity with a local embedding model; None when sentence-transformers is absent."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    encoder = SentenceTransformer(model, device="cpu")
    va, vb = encoder.encode([a, b], normalize_embeddings=True)
    return round(float((va * vb).sum()), 4)
