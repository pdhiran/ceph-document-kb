"""Fastembed ONNX embedding + FAISS index building."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from ceph_doc_kb.models import DocChunk

if TYPE_CHECKING:
    import faiss

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_DIMENSIONS = 384


class Embedder:
    """Wraps fastembed for document and query embedding."""

    def __init__(self, model_name: str = DEFAULT_MODEL):
        from fastembed import TextEmbedding
        self._model = TextEmbedding(model_name=model_name)
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        """Embed a list of document texts. Returns (N, dim) float32 array."""
        embeddings = list(self._model.embed(texts))
        return np.array(embeddings, dtype=np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        """Embed a single query. Returns (1, dim) float32 array."""
        embeddings = list(self._model.embed([query]))
        return np.array(embeddings, dtype=np.float32)


class IndexBuilder:
    """Builds per-component FAISS indices from document chunks."""

    def __init__(self, embedder: Embedder | None = None, model_name: str = DEFAULT_MODEL):
        self._embedder = embedder or Embedder(model_name)
        self.dimensions: int = DEFAULT_DIMENSIONS

    def build_component_index(
        self,
        chunks: list[DocChunk],
        output_dir: Path,
    ) -> int:
        """Build FAISS index + chunks.json for a single component.

        Returns number of chunks indexed.
        """
        import faiss

        if not chunks:
            return 0

        output_dir.mkdir(parents=True, exist_ok=True)

        texts = [f"{c.title}\n{c.content}" for c in chunks]

        logger.info(f"Embedding {len(texts)} chunks...")
        embeddings = self._embedder.embed_documents(texts)

        dim = embeddings.shape[1]
        self.dimensions = dim
        index = faiss.IndexFlatIP(dim)  # inner product (cosine on normalized vectors)
        faiss.normalize_L2(embeddings)
        index.add(embeddings)

        index_path = output_dir / "faiss.index"
        faiss.write_index(index, str(index_path))

        chunks_data = [c.to_dict() for c in chunks]
        chunks_path = output_dir / "chunks.json"
        chunks_path.write_text(json.dumps(chunks_data, indent=2))

        logger.info(f"Wrote {len(chunks)} chunks to {output_dir}")
        return len(chunks)

    def build_all_components(
        self,
        chunks_by_component: dict[str, list[DocChunk]],
        base_output_dir: Path,
    ) -> dict[str, int]:
        """Build indices for all components. Returns {component: chunk_count}."""
        results = {}
        for component, chunks in sorted(chunks_by_component.items()):
            if not chunks:
                continue
            output_dir = base_output_dir / component
            count = self.build_component_index(chunks, output_dir)
            results[component] = count
            logger.info(f"  {component}: {count} chunks")
        return results
