"""Tests for date-based and tag-based incremental indexing helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ceph_doc_kb.indexer.incremental import (
    get_changed_files,
    get_changed_files_since,
    parse_since_date,
)


def test_parse_since_date_accepts_iso():
    assert parse_since_date("2026-08-01") == "2026-08-01"


def test_parse_since_date_rejects_garbage():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_since_date("August 1")
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_since_date("2026/08/01")


def test_get_changed_files_since_dedupes_and_filters_rst():
    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = (
        "doc/rados/ops.rst\n"
        "doc/rados/ops.rst\n"
        "doc/cephfs/index.rst\n"
        "README.md\n"
        "\n"
        "src/osd.cc\n"
    )
    with patch("ceph_doc_kb.indexer.incremental.subprocess.run", return_value=fake) as run:
        files = get_changed_files_since(Path("/tmp/ceph"), "2026-08-01")

    assert files == ["doc/rados/ops.rst", "doc/cephfs/index.rst"]
    args = run.call_args[0][0]
    assert "--since=2026-08-01" in args
    assert "doc/" in args


def test_get_changed_files_since_raises_on_git_failure():
    fake = MagicMock()
    fake.returncode = 1
    fake.stderr = "not a git repo"
    with patch("ceph_doc_kb.indexer.incremental.subprocess.run", return_value=fake):
        with pytest.raises(RuntimeError, match="git log failed"):
            get_changed_files_since(Path("/tmp/ceph"), "2026-08-01")


def test_get_changed_files_tag_range():
    fake = MagicMock()
    fake.returncode = 0
    fake.stdout = "doc/rbd/mirror.rst\n"
    with patch("ceph_doc_kb.indexer.incremental.subprocess.run", return_value=fake) as run:
        files = get_changed_files(Path("/tmp/ceph"), "v20.2.1", "v20.2.2")

    assert files == ["doc/rbd/mirror.rst"]
    args = run.call_args[0][0]
    assert "v20.2.1..v20.2.2" in args
