"""Search router — two-tier search with component scoping and quality re-ranking."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ceph_doc_kb.constants import tokenize
from ceph_doc_kb.models import CodeExample, DocChunk, IndexMetadata, SearchResult
from ceph_doc_kb.search.keyword_search import BM25Search
from ceph_doc_kb.search.semantic_search import SemanticSearch

logger = logging.getLogger(__name__)

_DEFAULT_SEARCH_CONFIG = {
    "bm25_threshold": 0.25,
    "semantic_fallback_ratio": 0.5,
    "quality_boost_factor": 0.3,
    "default_limit": 10,
    "max_limit": 50,
}


class SearchRouter:
    """Two-tier search: BM25 keyword (Tier 1) + semantic (Tier 2), with quality re-ranking."""

    def __init__(self, knowledge_base_path: Path, config: dict | None = None) -> None:
        search_cfg = (config or {}).get("search", {})
        self._config = {**_DEFAULT_SEARCH_CONFIG, **search_cfg}
        self._bm25 = BM25Search()
        self._semantic = SemanticSearch()
        self._code_examples: dict[str, list[dict]] = {}
        self._chunks_by_component: dict[str, list[DocChunk]] = {}
        self._metadata: IndexMetadata | None = None

        self._load(knowledge_base_path)

    def _load(self, kb_path: Path) -> None:
        if not kb_path.is_dir():
            logger.warning("Knowledge base path does not exist: %s", kb_path)
            return

        meta_path = kb_path / "metadata.json"
        if meta_path.exists():
            try:
                self._metadata = IndexMetadata.load(meta_path)
            except Exception:
                logger.exception("Failed to load metadata from %s", meta_path)

        for child in sorted(kb_path.iterdir()):
            if not child.is_dir():
                continue
            component = child.name
            chunks = self._load_chunks(child / "chunks.json")
            if not chunks:
                continue

            self._chunks_by_component[component] = chunks
            self._bm25.add_component(component, chunks)
            self._semantic.load_component(
                component, child / "faiss.index", chunks
            )

            code_path = child / "code_examples.json"
            if code_path.exists():
                try:
                    examples = json.loads(code_path.read_text())
                    self._code_examples[component] = (
                        examples if isinstance(examples, list) else []
                    )
                except Exception:
                    logger.exception(
                        "Failed to load code examples for %s", component
                    )

    @staticmethod
    def _load_chunks(path: Path) -> list[DocChunk]:
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text())
            if not isinstance(raw, list):
                return []
            return [DocChunk.from_dict(item) for item in raw]
        except Exception:
            logger.exception("Failed to load chunks from %s", path)
            return []

    @property
    def components(self) -> list[str]:
        return sorted(set(self._bm25.components) | set(self._semantic.components))

    @property
    def metadata(self) -> IndexMetadata | None:
        return self._metadata

    def get_chunks_for_source(self, source_file: str) -> list[DocChunk]:
        """Get all chunks for a given source file (cached, no disk I/O)."""
        for chunks in self._chunks_by_component.values():
            matching = [c for c in chunks if c.source_file == source_file]
            if matching:
                return matching
        return []

    def search(
        self,
        query: str,
        component: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        bm25_results = self._bm25.search(query, component=component, limit=limit)

        threshold = self._config["bm25_threshold"]
        above = [r for r in bm25_results if r.score >= threshold]

        fallback_target = int(limit * self._config["semantic_fallback_ratio"])
        need_semantic = len(above) < max(fallback_target, 1)

        semantic_results: list[SearchResult] = []
        if need_semantic:
            semantic_limit = limit - len(above)
            semantic_results = self._semantic.search(
                query, component=component, limit=max(semantic_limit, 1)
            )

        merged = self._merge(bm25_results, semantic_results, limit)
        return self._rerank(merged, limit)

    def _merge(
        self,
        bm25: list[SearchResult],
        semantic: list[SearchResult],
        limit: int,
    ) -> list[SearchResult]:
        seen: dict[str, SearchResult] = {}

        for r in bm25:
            eid = r.chunk.entity_id
            if eid not in seen or r.score > seen[eid].score:
                seen[eid] = r

        min_sem = 0.0
        sem_range = 0.0
        if semantic:
            max_sem = max(r.score for r in semantic)
            min_sem = min(r.score for r in semantic)
            sem_range = max_sem - min_sem

        for r in semantic:
            normalized_score = (
                (r.score - min_sem) / sem_range if sem_range > 0 else 1.0
            )
            eid = r.chunk.entity_id
            if eid in seen:
                existing = seen[eid]
                combined = (existing.score + normalized_score) / 2.0
                seen[eid] = SearchResult(
                    chunk=existing.chunk, score=combined, source="merged"
                )
            else:
                seen[eid] = SearchResult(
                    chunk=r.chunk, score=normalized_score, source="semantic"
                )

        results = sorted(seen.values(), key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _rerank(self, results: list[SearchResult], limit: int) -> list[SearchResult]:
        boost = self._config["quality_boost_factor"]
        scored: list[tuple[float, SearchResult]] = []
        for r in results:
            final = r.score * (1 + boost * r.chunk.quality_score)
            scored.append((
                final,
                SearchResult(chunk=r.chunk, score=final, source=r.source),
            ))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [sr for _, sr in scored[:limit]]

    def search_code_examples(
        self,
        query: str,
        component: str | None = None,
        language: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        targets = (
            {component: self._code_examples[component]}
            if component and component in self._code_examples
            else self._code_examples
        )
        if not targets:
            return []

        query_terms = set(tokenize(query))
        if not query_terms:
            return []

        scored: list[tuple[float, dict]] = []
        for examples in targets.values():
            for ex in examples:
                if language and ex.get("language", "") != language:
                    continue
                text = f"{ex.get('context', '')} {ex.get('code', '')} {ex.get('section_title', '')}".lower()
                hits = sum(1 for t in query_terms if t in text)
                if hits == 0:
                    continue
                score = hits / len(query_terms)
                scored.append((score, ex))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [ex for _, ex in scored[:limit]]
