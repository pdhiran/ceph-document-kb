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
    assert "--transport" in help_text
    assert "sse" in help_text
    assert "8082" in help_text


def test_rest_api_imports():
    from ceph_doc_kb.server import rest_api
    assert hasattr(rest_api, "create_app")
