"""Tests for MCP server tool definitions."""

import pytest


def test_mcp_server_imports():
    from ceph_doc_kb.server import mcp_server
    assert hasattr(mcp_server, "main")


def test_mcp_help_documents_sse():
    from ceph_doc_kb.server.mcp_server import main
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with pytest.raises(SystemExit) as exc, redirect_stdout(buf):
        main(["--help"])
    assert exc.value.code == 0
    help_text = buf.getvalue()
    compact = " ".join(help_text.split())
    assert "--transport" in help_text
    assert "sse" in help_text
    assert "8082" in help_text
    assert "--no-auto-update" in help_text
    assert "disables both git pull and the trigger watcher" in compact


def test_readme_clone_cd_matches_github():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text()
    assert "github.com/pdhiran/ceph-document-kb.git" in readme
    assert "cd ceph-document-kb" in readme
    assert "Python package and Cursor MCP key are `ceph-doc-kb`" in readme
    assert '"cwd": "/path/to/ceph-document-kb"' in readme

    leftover = (
        "cd ceph-doc-kb",
        "/path/to/ceph-doc-kb",
        "ceph-doc-kb/\n",
    )
    for rel in ("README.md", "UPDATING.md", "DEVELOPMENT.md", "vscode-extension/README.md"):
        text = (root / rel).read_text()
        assert "ceph-document-kb" in text, f"{rel} missing clone dir ceph-document-kb"
        for needle in leftover:
            assert needle not in text, f"{rel} leftover clone/cwd path {needle!r}"
    updating = (root / "UPDATING.md").read_text()
    assert '"cwd": "/path/to/ceph-document-kb"' in updating
    assert "ceph-document-kb/\n" in (root / "DEVELOPMENT.md").read_text()


def test_list_versions_ibm_primary_is_not_labeled_upstream(tmp_path):
    import json

    from ceph_doc_kb.server.mcp_server import CephDocMCPServer

    ibm = tmp_path / "knowledge" / "doc-ibm-9.1"
    ibm.mkdir(parents=True)
    (ibm / "metadata.json").write_text(json.dumps({
        "version": "1",
        "ceph_version": "ibm-9.1",
        "embedding_model": "x",
        "embedding_dimensions": 8,
        "total_chunks": 1,
    }))
    srv = CephDocMCPServer(ibm, {})
    srv._load()
    versions = srv._list_versions()
    assert versions[0]["version_id"] == "ibm-9.1"
    assert versions[0]["type"] == "ibm-downstream"


def test_create_server_rediscovers_ibm(tmp_path):
    import json

    from unittest.mock import patch

    from ceph_doc_kb.server.mcp_server import CephDocMCPServer, create_server

    def meta(ceph: str) -> str:
        return json.dumps({
            "version": "1",
            "ceph_version": ceph,
            "embedding_model": "x",
            "embedding_dimensions": 8,
            "total_chunks": 1,
        })

    knowledge = tmp_path / "knowledge"
    primary = knowledge / "doc-20.2.1"
    ibm = knowledge / "doc-ibm-9.1"
    primary.mkdir(parents=True)
    ibm.mkdir(parents=True)
    (primary / "metadata.json").write_text(meta("20.2.1"))
    (ibm / "metadata.json").write_text(meta("ibm-9.1"))
    (ibm / "command_xref.json").write_text(json.dumps({"ceph osd ls": [{"page": "x"}]}))

    with (
        patch("ceph_doc_kb.search.router.SearchRouter"),
        patch("ceph_doc_kb.server.mcp_server.Server"),
    ):
        _mcp, doc_server = create_server(kb_path=str(knowledge))

    assert isinstance(doc_server, CephDocMCPServer)
    assert len(doc_server._additional_metadata) == 1
    assert doc_server._additional_metadata[0].ceph_version == "ibm-9.1"


def test_rest_create_loads_ibm_additional(tmp_path):
    import json

    from unittest.mock import patch

    from ceph_doc_kb.server.rest_api import _create_doc_server

    def meta(ceph: str) -> str:
        return json.dumps({
            "version": "1",
            "ceph_version": ceph,
            "embedding_model": "x",
            "embedding_dimensions": 8,
            "total_chunks": 1,
        })

    knowledge = tmp_path / "knowledge"
    primary = knowledge / "doc-20.2.1"
    ibm = knowledge / "doc-ibm-9.1"
    primary.mkdir(parents=True)
    ibm.mkdir(parents=True)
    (primary / "metadata.json").write_text(meta("20.2.1"))
    (ibm / "metadata.json").write_text(meta("ibm-9.1"))

    with patch("ceph_doc_kb.search.router.SearchRouter"):
        srv = _create_doc_server(str(knowledge), None)

    assert len(srv._additional_metadata) == 1
    assert srv._additional_metadata[0].ceph_version == "ibm-9.1"


def test_rest_api_imports():
    from ceph_doc_kb.server import rest_api
    assert hasattr(rest_api, "create_app")
