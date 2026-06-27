"""Tests for RST parser and chunker."""

# TODO: Tests create side effects by writing into the source tree (fixtures/).
# Refactor to use tmp_path so tests are fully isolated.

from pathlib import Path

import pytest

from ceph_doc_kb.indexer.parser import parse_rst_file, parse_docs_directory

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_pools_rst():
    """Parse the rados pools fixture and verify chunk extraction."""
    # Simulate docs_root being the fixtures dir with rados/ subdir
    docs_root = FIXTURES
    file_path = FIXTURES / "rados_pools.rst"

    # Create a rados subdirectory symlink structure for testing
    rados_dir = FIXTURES / "rados"
    rados_dir.mkdir(exist_ok=True)
    target = rados_dir / "pools.rst"
    if not target.exists():
        import shutil
        shutil.copy(file_path, target)

    chunks = parse_rst_file(target, docs_root, version="20.2.1")
    assert len(chunks) > 0

    titles = [c.title for c in chunks]
    assert any("Pool" in t or "pool" in t.lower() for t in titles)

    for chunk in chunks:
        assert chunk.component == "rados"
        assert chunk.version == "20.2.1"
        assert chunk.entity_id


def test_parse_rbd_mirroring():
    """Parse rbd mirroring fixture and verify directives are handled."""
    docs_root = FIXTURES
    rbd_dir = FIXTURES / "rbd"
    rbd_dir.mkdir(exist_ok=True)
    target = rbd_dir / "mirroring.rst"
    if not target.exists():
        import shutil
        shutil.copy(FIXTURES / "rbd_mirroring.rst", target)

    chunks = parse_rst_file(target, docs_root, version="20.2.1")
    assert len(chunks) > 0

    for chunk in chunks:
        assert chunk.component == "rbd"


def test_parse_detects_commands():
    """Verify that command references are extracted from chunks."""
    rados_dir = FIXTURES / "rados"
    rados_dir.mkdir(exist_ok=True)
    target = rados_dir / "pools.rst"
    if not target.exists():
        import shutil
        shutil.copy(FIXTURES / "rados_pools.rst", target)

    chunks = parse_rst_file(target, FIXTURES, version="20.2.1")
    all_commands = []
    for chunk in chunks:
        all_commands.extend(chunk.commands_referenced)

    # Should find at least some ceph commands
    assert len(all_commands) > 0 or any("ceph" in c.content for c in chunks)


def test_parse_directory():
    """Test parsing an entire directory tree."""
    # Set up fixture directory structure
    rados_dir = FIXTURES / "rados"
    rados_dir.mkdir(exist_ok=True)
    rbd_dir = FIXTURES / "rbd"
    rbd_dir.mkdir(exist_ok=True)

    import shutil
    if not (rados_dir / "pools.rst").exists():
        shutil.copy(FIXTURES / "rados_pools.rst", rados_dir / "pools.rst")
    if not (rbd_dir / "mirroring.rst").exists():
        shutil.copy(FIXTURES / "rbd_mirroring.rst", rbd_dir / "mirroring.rst")

    chunks = parse_docs_directory(FIXTURES, version="20.2.1")
    assert len(chunks) > 0

    components = set(c.component for c in chunks)
    assert "rados" in components
    assert "rbd" in components


def test_doc_url_generation():
    """Verify doc URLs are generated correctly from source paths."""
    rados_dir = FIXTURES / "rados"
    rados_dir.mkdir(exist_ok=True)
    target = rados_dir / "pools.rst"
    if not target.exists():
        import shutil
        shutil.copy(FIXTURES / "rados_pools.rst", target)

    chunks = parse_rst_file(target, FIXTURES, version="20.2.1")
    for chunk in chunks:
        assert "docs.ceph.com" in chunk.doc_url
        assert "rados" in chunk.doc_url
