"""Tests for chunk quality scorer."""

import pytest

from ceph_doc_kb.models import DocChunk
from ceph_doc_kb.indexer.scorer import score_chunk, score_chunks


def _make_chunk(content: str, title: str = "Test", **kwargs) -> DocChunk:
    return DocChunk(
        entity_id="test123",
        title=title,
        content=content,
        component="rados",
        topic="operations",
        source_file="rados/test.rst",
        section_path="Test",
        doc_url="https://docs.ceph.com/en/latest/rados/test/",
        **kwargs,
    )


def test_code_block_boosts_score():
    """Chunks with code blocks score higher."""
    with_code = _make_chunk(
        "To create a pool:\n\n.. code-block:: bash\n\n   ceph osd pool create test 128\n\n"
        "This creates a pool with 128 placement groups."
    )
    without_code = _make_chunk(
        "Pools are logical partitions for storing objects in a Ceph cluster. "
        "They provide isolation and configuration boundaries for data."
    )

    assert score_chunk(with_code) > score_chunk(without_code)


def test_command_reference_boosts_score():
    """Chunks referencing Ceph commands score higher."""
    with_cmd = _make_chunk(
        "Use ceph osd pool create to make a new pool. You can also run "
        "rados bench to test performance. These are important operations."
    )
    without_cmd = _make_chunk(
        "Pools provide isolation between different workloads. Each pool "
        "can have its own replication factor and CRUSH rules defined."
    )

    assert score_chunk(with_cmd) > score_chunk(without_cmd)


def test_toc_penalized():
    """Table of contents chunks are penalized."""
    toc_chunk = _make_chunk(".. toctree::\n   :maxdepth: 2\n\n   pools\n   placement-groups")
    normal_chunk = _make_chunk(
        "This section describes how to configure pools, including setting "
        "the replication factor, placement group count, and compression options."
    )

    assert score_chunk(toc_chunk) < score_chunk(normal_chunk)


def test_short_content_penalized():
    """Very short chunks are penalized."""
    short = _make_chunk("See also: pools")
    long = _make_chunk(
        "Erasure coding is a data protection technique that splits data into fragments. "
        "Each fragment is stored on a different OSD. This provides space efficiency "
        "compared to full replication while maintaining data durability."
    )

    assert score_chunk(short) < score_chunk(long)


def test_score_chunks_modifies_in_place():
    """score_chunks should update quality_score on each chunk."""
    chunks = [
        _make_chunk(".. code-block:: bash\n\n   ceph status\n\nCheck the cluster health."),
        _make_chunk("Short"),
    ]
    result = score_chunks(chunks)
    assert result is chunks
    assert chunks[0].quality_score != 0.5  # default was changed
    assert chunks[1].quality_score != 0.5


def test_score_bounds():
    """Scores should be clamped to [0, 1]."""
    extreme_good = _make_chunk(
        ".. code-block:: bash\n\n   ceph osd pool create test 128\n\n"
        ".. warning:: Be careful!\n\n"
        "This is a very detailed explanation of pool creation that covers "
        "all the important aspects of configuring pools in production."
    )
    extreme_bad = _make_chunk(".. toctree::\n   x", deprecated=True)

    assert 0.0 <= score_chunk(extreme_good) <= 1.0
    assert 0.0 <= score_chunk(extreme_bad) <= 1.0
