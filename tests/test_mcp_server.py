"""Tests for MCP server tool definitions."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


def test_mcp_server_imports():
    """Verify MCP server module can be imported."""
    from ceph_doc_kb.server import mcp_server
    assert hasattr(mcp_server, 'main')


def test_rest_api_imports():
    """Verify REST API module can be imported."""
    from ceph_doc_kb.server import rest_api
    assert hasattr(rest_api, 'create_app')
