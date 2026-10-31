"""Lexical confidence score (0-1) for how well a document matches the query.

Used to decide when full text is worth fetching. The score is deliberately simple and
explainable, and is computed only from title + abstract:

    confidence = 0.55 * coverage        # share of query terms found in title/abstract
               + 0.20 * title_coverage  # share of query terms found in the title
               + 0.15 * proximity       # query terms appear next to each other (phrase match)
               + 0.10 * bm25_relative   # BM25 score relative to the best hit in this result set

Coverage terms use uniform weights (not IDF): every hit already matched the query at the
source, so pool-level IDF would just down-weight the very terms the user asked for.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from app.literature.models import Document

WEIGHTS = {"coverage": 0.55, "title": 0.20, "proximity": 0.15, "bm25": 0.10}
BM25_K1 = 1.2
BM25_B = 0.75

STOPWORDS = frozenset(
    """
    a an and are as at be but by for from has have in into is it its of on or not that the
    their then there these this to was were what when which while who will with within without
    via vs versus using use used based study studies effect effects role new novel analysis
    """.split()
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_FIELD_TAG_RE = re.compile(r"\[[^\]]*\]")  # PubMed field tags like [tiab], [MeSH Terms]


def _stem(token: str) -> str:
    """Very light plural folding so 'kinases' matches 'kinase'."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def tokenize(text: str | None) -> list[str]:
    if not text:
        return []
    return [_stem(t) for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


def query_terms(query: str) -> list[str]:
    """Ordered, de-duplicated content terms of the query (boolean operators and tags removed)."""
    return list(dict.fromkeys(tokenize(_FIELD_TAG_RE.sub(" ", query))))


def _proximity(terms: list[str], tokens: list[str], coverage: float) -> float:
    if len(terms) < 2:
        return coverage
    bigrams = set(zip(tokens, tokens[1:], strict=False))
    pairs = list(zip(terms, terms[1:], strict=False))
    return sum(1 for p in pairs if p in bigrams) / len(pairs)


def score_documents(query: str, documents: list[Document]) -> None:
    """Set ``document.confidence`` in place for every document."""
    terms = query_terms(query)
    if not documents:
        return
    if not terms:
        for doc in documents:
            doc.confidence = 0.0
        return

    term_set = set(terms)
    token_lists = [tokenize(d.title) + tokenize(d.abstract) for d in documents]
    n_docs = len(documents)
    avg_len = (sum(len(t) for t in token_lists) / n_docs) or 1.0
    doc_freq = Counter(t for tokens in token_lists for t in set(tokens) & term_set)

    bm25_scores = []
    for tokens in token_lists:
        counts = Counter(tokens)
        score = 0.0
        for term in terms:
            tf = counts.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (n_docs - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            norm = tf + BM25_K1 * (1 - BM25_B + BM25_B * len(tokens) / avg_len)
            score += idf * tf * (BM25_K1 + 1) / norm
        bm25_scores.append(score)
    best_bm25 = max(bm25_scores) or 1.0

    for doc, tokens, bm25 in zip(documents, token_lists, bm25_scores, strict=True):
        present = term_set & set(tokens)
        coverage = len(present) / len(term_set)
        title_coverage = len(term_set & set(tokenize(doc.title))) / len(term_set)
        proximity = _proximity(terms, tokens, coverage)
        confidence = (
            WEIGHTS["coverage"] * coverage
            + WEIGHTS["title"] * title_coverage
            + WEIGHTS["proximity"] * proximity
            + WEIGHTS["bm25"] * (bm25 / best_bm25)
        )
        doc.confidence = round(min(max(confidence, 0.0), 1.0), 3)
