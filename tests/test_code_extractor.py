"""Tests for code block extraction."""

from pathlib import Path

import pytest

from ceph_doc_kb.indexer.code_extractor import extract_code_blocks, extract_from_file

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_code_blocks_from_rst():
    """Extract code blocks from pools RST fixture."""
    content = (FIXTURES / "rados_pools.rst").read_text()
    examples = extract_code_blocks(content, "rados/pools.rst", "rados")

    assert len(examples) > 0

    languages = [e.language for e in examples]
    assert "bash" in languages

    bash_examples = [e for e in examples if e.language == "bash"]
    assert any("ceph osd pool" in e.code for e in bash_examples)


def test_extract_json_code_block():
    """Verify JSON code blocks are extracted."""
    content = (FIXTURES / "rados_pools.rst").read_text()
    examples = extract_code_blocks(content, "rados/pools.rst", "rados")

    json_examples = [e for e in examples if e.language == "json"]
    assert len(json_examples) > 0


def test_command_detection():
    """Verify Ceph commands are detected in code blocks."""
    content = (FIXTURES / "cephadm_install.rst").read_text()
    examples = extract_code_blocks(content, "cephadm/install.rst", "cephadm")

    all_commands = []
    for ex in examples:
        all_commands.extend(ex.commands_used)

    assert len(all_commands) > 0


def test_extract_from_file():
    """Test the file-level extraction function."""
    rados_dir = FIXTURES / "rados"
    rados_dir.mkdir(exist_ok=True)
    target = rados_dir / "pools.rst"
    if not target.exists():
        import shutil
        shutil.copy(FIXTURES / "rados_pools.rst", target)

    examples = extract_from_file(target, FIXTURES)
    assert len(examples) > 0
    assert all(e.component == "rados" for e in examples)


def test_yaml_code_block():
    """Verify YAML blocks are handled."""
    content = (FIXTURES / "cephadm_install.rst").read_text()
    examples = extract_code_blocks(content, "cephadm/install.rst", "cephadm")

    yaml_examples = [e for e in examples if e.language == "yaml"]
    assert len(yaml_examples) > 0
