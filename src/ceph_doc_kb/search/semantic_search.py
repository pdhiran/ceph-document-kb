"""Fastembed + FAISS semantic search over doc chunks (Tier 2)."""

from __future__ import annotations

import logging
from pathlib import Path

import faiss
import numpy as np

from ceph_doc_kb.models import DocChunk, SearchResult

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

_encoder = None


def _get_encoder():
    global _encoder
    if _encoder is None:
        from fastembed import TextEmbedding

        _encoder = TextEmbedding(model_name=EMBEDDING_MODEL)
    return _encoder


def _embed(texts: list[str]) -> np.ndarray:
    encoder = _get_encoder()
    embeddings = list(encoder.embed(texts))
    return np.array(embeddings, dtype=np.float32)


class _ComponentSemanticIndex:
    __slots__ = ("index", "chunks")

    def __init__(self, index: faiss.Index, chunks: list[DocChunk]) -> None:
        self.index = index
        self.chunks = chunks


class SemanticSearch:
    """Per-component FAISS semantic search using fastembed embeddings."""

    def __init__(self) -> None:
        self._indices: dict[str, _ComponentSemanticIndex] = {}

    def load_component(
        self, component: str, faiss_path: Path, chunks: list[DocChunk]
    ) -> None:
        if not faiss_path.exists():
            logger.warning("FAISS index not found: %s", faiss_path)
            return
        if not chunks:
            return
        try:
            index = faiss.read_index(str(faiss_path))
        except Exception:
            logger.exception("Failed to read FAISS index: %s", faiss_path)
            return
        if index.ntotal != len(chunks):
            logger.warning(
                "FAISS index size (%d) != chunk count (%d) for %s; skipping",
                index.ntotal,
                len(chunks),
                component,
            )
            return
        self._indices[component] = _ComponentSemanticIndex(index, chunks)

    @property
    def components(self) -> list[str]:
        return list(self._indices)

    def search(
        self,
        query: str,
        component: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        targets = (
            {component: self._indices[component]}
            if component and component in self._indices
            else self._indices
        )
        if not targets:
            return []

        query_vec = _embed([query])
        faiss.normalize_L2(query_vec)

        raw: list[tuple[float, DocChunk]] = []

        for comp_idx in targets.values():
            k = min(limit, comp_idx.index.ntotal)
            if k == 0:
                continue
            distances, ids = comp_idx.index.search(query_vec, k)
            for dist, idx in zip(distances[0], ids[0]):
                if idx < 0:
                    continue
                score = float(dist)
                if score > 0:
                    raw.append((score, comp_idx.chunks[idx]))

        if not raw:
            return []

        raw.sort(key=lambda x: x[0], reverse=True)
        return [
            SearchResult(chunk=chunk, score=score, source="semantic")
            for score, chunk in raw[:limit]
        ]
