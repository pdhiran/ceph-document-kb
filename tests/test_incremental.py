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


def test_index_docs_cli_since_calls_incremental(monkeypatch, tmp_path):
    import index_docs as idx

    docs = tmp_path / "doc"
    docs.mkdir()
    out = tmp_path / "kb"
    out.mkdir()
    monkeypatch.setattr(
        sys, "argv",
        [
            "index_docs.py",
            "--since", "2026-08-01",
            "--docs-path", str(docs),
            "--repo-path", str(tmp_path),
            "--version", "20.2.1",
            "--output", str(out),
        ],
    )
    called: dict = {}

    def fake_inc(**kwargs):
        called.update(kwargs)
        meta = MagicMock()
        meta.ceph_version = "20.2.1"
        meta.total_chunks = 0
        meta.total_code_examples = 0
        meta.components = {}
        return meta

    monkeypatch.setattr(
        "ceph_doc_kb.indexer.incremental.incremental_update", fake_inc,
    )
    rc = idx.main()
    assert rc == 0
    assert called["since"] == "2026-08-01"
    assert called["to_version"] == "20.2.1"
    assert called["docs_path"] == docs
    assert called["repo_path"] == tmp_path
    assert called["index_path"] == out


def test_incremental_since_empty_git_log_skips_embed(tmp_path):
    docs = tmp_path / "doc"
    docs.mkdir()
    index = tmp_path / "kb"
    comp = index / "rados"
    comp.mkdir(parents=True)
    chunk = {
        "entity_id": "a" * 16,
        "title": "keep",
        "content": "old",
        "component": "rados",
        "topic": "ops",
        "source_file": "rados/keep.rst",
        "section_path": "keep",
        "doc_url": "http://x",
    }
    (comp / "chunks.json").write_text(json.dumps([chunk]))
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
            return_value=[],
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
    assert result.last_incremental_since == "2026-08-01"
    kept = json.loads((comp / "chunks.json").read_text())
    assert kept[0]["content"] == "old"


def test_since_paths_in_source():
    inc = (REPO / "src/ceph_doc_kb/indexer/incremental.py").read_text()
    assert '"git", "log"' in inc
    assert 'f"--since={since}"' in inc
    assert "existing_chunks +" in inc

    ibm = (REPO / "index_ibm_docs.py").read_text()
    assert "pages = _crawl_live(args)" in ibm
    assert "_changed_pages_vs_cache" in ibm
    assert "skipping rebuild" in ibm
    assert "if args.since and not args.cache_dir:" in ibm
    assert "full IBM rebuild" in ibm
    skip_at = ibm.index("skipping rebuild")
    assert ibm.rfind("if args.cache_dir:", 0, skip_at) > ibm.index(
        "if args.since and not args.cache_dir:"
    )


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


def test_incremental_since_merges_changed_rst_keeps_others(tmp_path):
    """--since re-embeds only git-log files and keeps sibling RST chunks."""
    from ceph_doc_kb.models import DocChunk

    docs = tmp_path / "doc"
    (docs / "rados" / "operations").mkdir(parents=True)
    (docs / "rados" / "operations" / "pools.rst").write_text("Pools\n=====\n\nupdated\n")

    index = tmp_path / "kb"
    comp = index / "rados"
    comp.mkdir(parents=True)
    keep = {
        "entity_id": "b" * 16,
        "title": "keep",
        "content": "old keep",
        "component": "rados",
        "topic": "operations",
        "source_file": "rados/operations/keep.rst",
        "section_path": "keep",
        "doc_url": "http://x",
    }
    old_pools = {
        "entity_id": "c" * 16,
        "title": "pools",
        "content": "old pools",
        "component": "rados",
        "topic": "operations",
        "source_file": "rados/operations/pools.rst",
        "section_path": "pools",
        "doc_url": "http://x",
    }
    (comp / "chunks.json").write_text(json.dumps([keep, old_pools]))
    (comp / "faiss.index").write_text("fake")
    (comp / "code_examples.json").write_text("[]")
    (index / "metadata.json").write_text(json.dumps({
        "version": "1.0",
        "ceph_version": "20.2.1",
        "embedding_model": "x",
        "embedding_dimensions": 8,
        "total_chunks": 2,
        "total_code_examples": 0,
        "components": {
            "rados": {
                "name": "rados",
                "chunk_count": 2,
                "code_example_count": 0,
                "topics": ["operations"],
                "faiss_index_path": "rados/faiss.index",
                "chunks_path": "rados/chunks.json",
                "code_examples_path": "rados/code_examples.json",
            }
        },
    }))

    new_pools = DocChunk(
        entity_id="d" * 16,
        title="pools",
        content="new pools",
        component="rados",
        topic="operations",
        source_file="rados/operations/pools.rst",
        section_path="pools",
        doc_url="http://x",
    )

    def _write_chunks(chunks, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "chunks.json").write_text(
            json.dumps([c.to_dict() for c in chunks], indent=2)
        )
        (output_dir / "faiss.index").write_text("fake")
        return len(chunks)

    with (
        patch(
            "ceph_doc_kb.indexer.incremental.get_changed_files_since",
            return_value=["doc/rados/operations/pools.rst"],
        ),
        patch(
            "ceph_doc_kb.indexer.incremental.parse_rst_file",
            return_value=[new_pools],
        ),
        patch("ceph_doc_kb.indexer.incremental.extract_code_blocks", return_value=[]),
        patch("ceph_doc_kb.indexer.incremental.score_chunks"),
        patch("ceph_doc_kb.indexer.incremental.build_xref", return_value={}),
        patch("ceph_doc_kb.indexer.incremental.save_xref"),
        patch("ceph_doc_kb.indexer.incremental.Embedder"),
        patch("ceph_doc_kb.indexer.incremental.IndexBuilder") as ib_cls,
    ):
        ib_cls.return_value.build_component_index.side_effect = _write_chunks
        result = incremental_update(
            docs_path=docs,
            repo_path=tmp_path,
            index_path=index,
            to_version="20.2.1",
            since="2026-08-01",
        )

    data = json.loads((comp / "chunks.json").read_text())
    by_src = {d["source_file"]: d for d in data}
    assert "rados/operations/keep.rst" in by_src
    assert by_src["rados/operations/keep.rst"]["content"] == "old keep"
    assert by_src["rados/operations/pools.rst"]["content"] == "new pools"
    assert result.last_incremental_since == "2026-08-01"
    assert result.total_chunks == 2


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


def _minimal_ibm_metadata() -> str:
    return json.dumps({
        "version": "1.0",
        "ceph_version": "ibm-9.1",
        "embedding_model": "x",
        "embedding_dimensions": 8,
        "total_chunks": 1,
        "total_code_examples": 0,
        "components": {},
    })


def test_ibm_since_without_cache_full_rebuilds(monkeypatch, tmp_path, capsys):
    """--since with no --cache-dir must rebuild, not skip FAISS."""
    import index_ibm_docs as ibm
    from ceph_doc_kb.models import DocChunk

    out = tmp_path / "doc-ibm-9.1"
    chunk = DocChunk(
        entity_id="a" * 16,
        title="t",
        content="c",
        component="cephadm",
        topic="install",
        source_file="ibm-docs/9.1/a",
        section_path="t",
        doc_url="http://x",
    )
    pages = [{
        "url": "http://x",
        "topic_slug": "a",
        "html": "<p>x</p>",
        "label": "a",
        "parent_section": "",
    }]

    monkeypatch.setattr(
        sys, "argv",
        [
            "index_ibm_docs.py",
            "--version", "9.1",
            "--since", "2026-08-01",
            "--output", str(out),
        ],
    )
    monkeypatch.setattr(ibm, "_crawl_live", lambda args: pages)
    monkeypatch.setattr(
        "ceph_doc_kb.indexer.ibm_parser.parse_ibm_page",
        lambda **kwargs: [chunk],
    )
    monkeypatch.setattr(
        "ceph_doc_kb.indexer.ibm_parser.extract_code_examples_from_page",
        lambda **kwargs: [],
    )
    monkeypatch.setattr("ceph_doc_kb.indexer.scorer.score_chunks", lambda chunks: None)
    monkeypatch.setattr("ceph_doc_kb.indexer.xref.build_xref", lambda chunks: {})
    monkeypatch.setattr("ceph_doc_kb.indexer.xref.save_xref", lambda *a, **k: None)
    monkeypatch.setattr("ceph_doc_kb.indexer.embedder.Embedder", MagicMock)

    class FakeBuilder:
        dimensions = 8

        def __init__(self, *a, **k):
            pass

        def build_all_components(self, chunks_by_component, output):
            output.mkdir(parents=True, exist_ok=True)
            return {name: len(cs) for name, cs in chunks_by_component.items()}

    monkeypatch.setattr("ceph_doc_kb.indexer.embedder.IndexBuilder", FakeBuilder)

    rc = ibm.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert "without --cache-dir" in captured.err
    assert "skipping rebuild" not in captured.out
    assert (out / "metadata.json").exists()
    meta = json.loads((out / "metadata.json").read_text())
    assert meta["last_incremental_since"] == "2026-08-01"


def test_ibm_since_with_cache_skips_identical_rebuild(monkeypatch, tmp_path, capsys):
    import index_ibm_docs as ibm

    cache = tmp_path / "cache"
    _write_ibm_cache(cache, [("a", "<p>one</p>")])
    out = tmp_path / "doc-ibm-9.1"
    out.mkdir()
    (out / "metadata.json").write_text(_minimal_ibm_metadata())
    (out / "ibm_crawl_metadata.json").write_text("{}")

    monkeypatch.setattr(
        sys, "argv",
        [
            "index_ibm_docs.py",
            "--version", "9.1",
            "--since", "2026-08-01",
            "--cache-dir", str(cache),
            "--output", str(out),
        ],
    )
    monkeypatch.setattr(
        ibm, "_crawl_live",
        lambda args: [{"topic_slug": "a", "html": "<p>one</p>"}],
    )

    def _must_not_parse(**kwargs):
        raise AssertionError("identical cache must skip FAISS rebuild")

    monkeypatch.setattr("ceph_doc_kb.indexer.ibm_parser.parse_ibm_page", _must_not_parse)

    rc = ibm.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert "skipping rebuild" in captured.out


def test_ibm_cli_rejects_bad_since(monkeypatch, capsys):
    import index_ibm_docs as ibm

    monkeypatch.setattr(
        sys, "argv",
        ["index_ibm_docs.py", "--version", "9.1", "--since", "not-a-date"],
    )

    def _must_not_crawl(args):
        raise AssertionError("invalid --since must not crawl IBM")

    monkeypatch.setattr(ibm, "_crawl_live", _must_not_crawl)
    rc = ibm.main()
    assert rc == 1
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_ibm_since_with_cache_changed_rebuilds(monkeypatch, tmp_path, capsys):
    import index_ibm_docs as ibm
    from ceph_doc_kb.models import DocChunk

    cache = tmp_path / "cache"
    _write_ibm_cache(cache, [("a", "<p>old</p>")])
    out = tmp_path / "doc-ibm-9.1"
    out.mkdir()
    (out / "metadata.json").write_text(_minimal_ibm_metadata())

    chunk = DocChunk(
        entity_id="a" * 16,
        title="t",
        content="c",
        component="cephadm",
        topic="install",
        source_file="ibm-docs/9.1/a",
        section_path="t",
        doc_url="http://x",
    )
    pages = [{
        "url": "http://x",
        "topic_slug": "a",
        "html": "<p>new</p>",
        "label": "a",
        "parent_section": "",
    }]

    monkeypatch.setattr(
        sys, "argv",
        [
            "index_ibm_docs.py",
            "--version", "9.1",
            "--since", "2026-08-01",
            "--cache-dir", str(cache),
            "--output", str(out),
        ],
    )
    monkeypatch.setattr(ibm, "_crawl_live", lambda args: pages)
    monkeypatch.setattr(
        "ceph_doc_kb.indexer.ibm_parser.parse_ibm_page",
        lambda **kwargs: [chunk],
    )
    monkeypatch.setattr(
        "ceph_doc_kb.indexer.ibm_parser.extract_code_examples_from_page",
        lambda **kwargs: [],
    )
    monkeypatch.setattr("ceph_doc_kb.indexer.scorer.score_chunks", lambda chunks: None)
    monkeypatch.setattr("ceph_doc_kb.indexer.xref.build_xref", lambda chunks: {})
    monkeypatch.setattr("ceph_doc_kb.indexer.xref.save_xref", lambda *a, **k: None)
    monkeypatch.setattr("ceph_doc_kb.indexer.embedder.Embedder", MagicMock)

    class FakeBuilder:
        dimensions = 8

        def __init__(self, *a, **k):
            pass

        def build_all_components(self, chunks_by_component, output):
            output.mkdir(parents=True, exist_ok=True)
            return {name: len(cs) for name, cs in chunks_by_component.items()}

    monkeypatch.setattr("ceph_doc_kb.indexer.embedder.IndexBuilder", FakeBuilder)

    rc = ibm.main()
    captured = capsys.readouterr()
    assert rc == 0
    assert "skipping rebuild" not in captured.out
    assert "pages changed" in captured.out
    meta = json.loads((out / "metadata.json").read_text())
    assert meta["last_incremental_since"] == "2026-08-01"
