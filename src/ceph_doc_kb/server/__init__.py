"""MCP server and REST API for Ceph documentation KB."""

from ceph_doc_kb.server.mcp_server import create_server
from ceph_doc_kb.server.rest_api import create_app

__all__ = ["create_server", "create_app"]
