"""Tests for date-based and tag-based incremental indexing helpers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ceph_doc_kb.indexer.incremental import (
    _component_for_rel,
    get_changed_files,
    get_changed_files_since,
    incremental_update,
    parse_since_date,
)

REPO = Path(__file__).resolve().parents[1]


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


def test_component_for_rel_matches_parser():
    assert _component_for_rel("glossary.rst") == "unknown"
    assert _component_for_rel("rados/operations/pools.rst") == "rados"


def test_index_docs_cli_rejects_bad_since():
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "index_docs.py"),
            "--since", "not-a-date",
            "--docs-path", "/tmp",
            "--version", "20.2.1",
            "--repo-path", "/tmp",
        ],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 1
    assert "YYYY-MM-DD" in result.stderr


def test_incremental_purges_component_when_all_rst_deleted(tmp_path):
    docs = tmp_path / "doc"
    docs.mkdir()
    index = tmp_path / "kb"
    comp = index / "rados"
    comp.mkdir(parents=True)
    chunk = {
        "entity_id": "abc123abc123abcd",
        "title": "gone",
        "content": "x",
        "component": "rados",
        "topic": "ops",
        "source_file": "rados/gone.rst",
        "section_path": "gone",
        "doc_url": "http://x",
    }
    (comp / "chunks.json").write_text(json.dumps([chunk]))
    (comp / "faiss.index").write_text("fake")
    (comp / "code_examples.json").write_text("[]")
    (index / "metadata.json").write_text(json.dumps({
        "version": "1.0",
        "ceph_version": "20.2.1",
        "embedding_model": "x",
        "embedding_dimensions": 8,
        "total_chunks": 1,
        "total_code_examples": 0,
        "components": {
            "rados": {
                "name": "rados",
                "chunk_count": 1,
                "code_example_count": 0,
                "topics": ["ops"],
                "faiss_index_path": "rados/faiss.index",
                "chunks_path": "rados/chunks.json",
                "code_examples_path": "rados/code_examples.json",
            }
        },
    }))

    with (
        patch(
            "ceph_doc_kb.indexer.incremental.get_changed_files_since",
            return_value=["doc/rados/gone.rst"],
        ),
        patch("ceph_doc_kb.indexer.incremental.Embedder") as emb,
    ):
        result = incremental_update(
            docs_path=docs,
            repo_path=tmp_path,
            index_path=index,
            to_version="20.2.1",
            since="2026-08-01",
        )

    emb.assert_not_called()
    assert not (comp / "chunks.json").exists()
    assert not (comp / "faiss.index").exists()
    assert not (comp / "code_examples.json").exists()
    assert "rados" not in result.components


def _write_ibm_cache(cache_dir: Path, pages: list[tuple[str, str]]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for slug, html in pages:
        filename = f"{slug}.html"
        (cache_dir / filename).write_text(html)
        manifest.append({
            "url": f"http://example/{slug}",
            "topic_slug": slug,
            "label": slug,
            "parent_section": "",
            "filename": filename,
        })
    (cache_dir / "manifest.json").write_text(json.dumps(manifest))


def test_ibm_cache_identical_pages_are_unchanged(tmp_path):
    import index_ibm_docs as ibm

    _write_ibm_cache(tmp_path, [("a", "<p>one</p>")])
    pages = [{"topic_slug": "a", "html": "<p>one</p>"}]
    assert ibm._changed_pages_vs_cache(pages, tmp_path) == []


def test_ibm_cache_html_change_is_detected(tmp_path):
    import index_ibm_docs as ibm

    _write_ibm_cache(tmp_path, [("a", "<p>old</p>")])
    pages = [{"topic_slug": "a", "html": "<p>new</p>"}]
    changed = ibm._changed_pages_vs_cache(pages, tmp_path)
    assert [p["topic_slug"] for p in changed] == ["a"]


def test_ibm_cache_deleted_topic_forces_rebuild(tmp_path):
    import index_ibm_docs as ibm

    _write_ibm_cache(tmp_path, [("keep", "<p>same</p>"), ("gone", "<p>x</p>")])
    pages = [{"topic_slug": "keep", "html": "<p>same</p>"}]
    changed = ibm._changed_pages_vs_cache(pages, tmp_path)
    assert changed, "deletions must not skip the FAISS rebuild"
    assert [p["topic_slug"] for p in changed] == ["keep"]


def test_ibm_since_without_cache_warns(monkeypatch, capsys):
    import index_ibm_docs as ibm

    monkeypatch.setattr(
        sys, "argv",
        ["index_ibm_docs.py", "--version", "9.1", "--since", "2026-08-01"],
    )
    monkeypatch.setattr(ibm, "_crawl_live", lambda args: [])
    rc = ibm.main()
    assert rc == 1
    err = capsys.readouterr().err
    assert "without --cache-dir" in err
    assert "full IBM rebuild" in err
