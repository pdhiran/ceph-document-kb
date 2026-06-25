"""BM25 keyword search over doc chunks (Tier 1)."""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from ceph_doc_kb.constants import tokenize
from ceph_doc_kb.models import DocChunk, SearchResult


@dataclass
class _BM25Index:
    bm25: BM25Okapi
    chunks: list[DocChunk]


def build_bm25_index(chunks: list[DocChunk]) -> _BM25Index | None:
    if not chunks:
        return None
    corpus = [tokenize(f"{c.title} {c.content}") for c in chunks]
    if not any(corpus):
        return None
    return _BM25Index(bm25=BM25Okapi(corpus), chunks=chunks)


class BM25Search:
    """Per-component BM25 keyword search."""

    def __init__(self) -> None:
        self._indices: dict[str, _BM25Index] = {}

    def add_component(self, component: str, chunks: list[DocChunk]) -> None:
        idx = build_bm25_index(chunks)
        if idx is not None:
            self._indices[component] = idx

    @property
    def components(self) -> list[str]:
        return list(self._indices)

    def search(
        self,
        query: str,
        component: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        tokens = tokenize(query)
        if not tokens:
            return []

        targets = (
            {component: self._indices[component]}
            if component and component in self._indices
            else self._indices
        )
        if not targets:
            return []

        raw: list[tuple[float, DocChunk]] = []
        for idx in targets.values():
            scores = idx.bm25.get_scores(tokens)
            for i, score in enumerate(scores):
                if score > 0:
                    raw.append((float(score), idx.chunks[i]))

        if not raw:
            return []

        top = heapq.nlargest(limit, raw, key=lambda x: x[0])
        max_score = top[0][0]

        if max_score <= 0:
            return []

        return [
            SearchResult(
                chunk=chunk,
                score=score / max_score,
                source="bm25",
            )
            for score, chunk in top
        ]
