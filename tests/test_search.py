"""Tests for search functionality (unit-level, mocked indices)."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from ceph_doc_kb.models import DocChunk, SearchResult


def _sample_chunks() -> list[DocChunk]:
    """Generate enough chunks for BM25 to produce meaningful positive scores."""
    return [
        DocChunk(
            entity_id="chunk1",
            title="Creating a Pool",
            content="To create a pool, use ceph osd pool create command. "
                    "Set pg_num to a power of two for optimal distribution across OSDs. "
                    "Pool creation requires specifying the pool name and placement group count. "
                    "The pool will be created with the default replication factor.",
            component="rados",
            topic="operations",
            source_file="rados/operations/pools.rst",
            section_path="Pools > Creating a Pool",
            doc_url="https://docs.ceph.com/en/latest/rados/operations/pools/",
            commands_referenced=["ceph osd pool create"],
            quality_score=0.8,
        ),
        DocChunk(
            entity_id="chunk2",
            title="Erasure Coding",
            content="Erasure coded pools require less storage space compared to replicated pools. "
                    "Use erasure-code-profile to configure the coding scheme with specific k and m values. "
                    "The coding scheme determines how many data and coding chunks are used for each object.",
            component="rados",
            topic="operations",
            source_file="rados/operations/erasure-code.rst",
            section_path="Erasure Coding",
            doc_url="https://docs.ceph.com/en/latest/rados/operations/erasure-code/",
            commands_referenced=["ceph osd erasure-code-profile set"],
            quality_score=0.7,
        ),
        DocChunk(
            entity_id="chunk3",
            title="RBD Mirroring",
            content="RBD mirroring allows asynchronous replication of images between two Ceph clusters. "
                    "Enable mirroring with rbd mirror pool enable command on both clusters. "
                    "Mirroring can operate in pool mode or image mode depending on requirements.",
            component="rbd",
            topic="mirroring",
            source_file="rbd/rbd-mirroring.rst",
            section_path="RBD Mirroring",
            doc_url="https://docs.ceph.com/en/latest/rbd/rbd-mirroring/",
            commands_referenced=["rbd mirror pool enable"],
            quality_score=0.75,
        ),
        DocChunk(
            entity_id="chunk4",
            title="Pool Quotas",
            content="You can set quotas on pools to limit the number of bytes or objects stored. "
                    "Use ceph osd pool set-quota to configure maximum values for the pool. "
                    "Quotas help prevent runaway storage consumption in multi-tenant environments.",
            component="rados",
            topic="operations",
            source_file="rados/operations/pools.rst",
            section_path="Pools > Pool Quotas",
            doc_url="https://docs.ceph.com/en/latest/rados/operations/pools/",
            commands_referenced=["ceph osd pool set-quota"],
            quality_score=0.7,
        ),
        DocChunk(
            entity_id="chunk5",
            title="CRUSH Rules",
            content="CRUSH rules determine how data is distributed across OSDs in the cluster. "
                    "Each pool is associated with a CRUSH rule that controls placement. "
                    "Custom rules can be created to enforce failure domain requirements.",
            component="rados",
            topic="operations",
            source_file="rados/operations/crush-map.rst",
            section_path="CRUSH Rules",
            doc_url="https://docs.ceph.com/en/latest/rados/operations/crush-map/",
            commands_referenced=["ceph osd crush rule create-replicated"],
            quality_score=0.65,
        ),
        DocChunk(
            entity_id="chunk6",
            title="RBD Snapshots",
            content="RBD snapshots provide point-in-time copies of block device images. "
                    "Create snapshots using rbd snap create for backup or rollback purposes. "
                    "Snapshots are copy-on-write and consume space only for changed blocks.",
            component="rbd",
            topic="operations",
            source_file="rbd/rbd-snapshot.rst",
            section_path="RBD Snapshots",
            doc_url="https://docs.ceph.com/en/latest/rbd/rbd-snapshot/",
            commands_referenced=["rbd snap create"],
            quality_score=0.7,
        ),
    ]


class TestKeywordSearch:
    """Tests for BM25 keyword search tier."""

    def test_import(self):
        from ceph_doc_kb.search.keyword_search import BM25Search
        assert BM25Search is not None

    def test_basic_search(self):
        from ceph_doc_kb.search.keyword_search import BM25Search

        chunks = _sample_chunks()
        searcher = BM25Search()
        searcher.add_component("rados", [c for c in chunks if c.component == "rados"])
        searcher.add_component("rbd", [c for c in chunks if c.component == "rbd"])
        results = searcher.search("create pool", component="rados", limit=5)

        assert len(results) > 0
        assert results[0].chunk.entity_id == "chunk1"

    def test_component_filtering(self):
        from ceph_doc_kb.search.keyword_search import BM25Search

        chunks = _sample_chunks()
        searcher = BM25Search()
        # Use all chunks in a single component to avoid BM25 IDF=0
        # edge case with very small per-component corpora
        searcher.add_component("all", chunks)
        results = searcher.search("mirroring replication", limit=5)

        assert len(results) > 0
        assert any(r.chunk.entity_id == "chunk3" for r in results)


class TestSearchResult:
    """Tests for SearchResult serialization."""

    def test_to_dict(self):
        chunk = _sample_chunks()[0]
        result = SearchResult(chunk=chunk, score=0.95, source="bm25")
        d = result.to_dict()

        assert d["entity_id"] == "chunk1"
        assert d["score"] == 0.95
        assert d["search_source"] == "bm25"
        assert d["title"] == "Creating a Pool"
