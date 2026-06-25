"""MCP server exposing Ceph documentation knowledge base tools."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from ceph_doc_kb.models import IndexMetadata

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _version_sort_key(path: Path) -> list[int]:
    """Parse version numbers from directory name for proper numeric sorting."""
    import re
    nums = re.findall(r'\d+', path.name)
    return [int(n) for n in nums] if nums else [0]


def _resolve_kb_path(kb_path: str | None, version: str | None) -> Path:
    base = Path(kb_path) if kb_path else PROJECT_ROOT / "knowledge"
    if not base.exists():
        raise FileNotFoundError(f"Knowledge base path does not exist: {base}")
    if version:
        versioned = base / version
        if versioned.exists():
            return versioned
        raise FileNotFoundError(f"Version '{version}' not found under {base}")
    versions = sorted(
        [d for d in base.iterdir() if d.is_dir() and (d / "metadata.json").exists()],
        key=_version_sort_key,
    )
    if versions:
        return versions[-1]
    return base


def _load_config(config_path: Path | None = None) -> dict:
    import yaml

    path = config_path or PROJECT_ROOT / "config.yaml"
    if path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


def _load_command_xref(kb_path: Path) -> dict[str, list[dict]]:
    xref_file = kb_path / "command_xref.json"
    if xref_file.exists():
        return json.loads(xref_file.read_text())
    return {}


def _build_tools() -> list[Tool]:
    return [
        Tool(
            name="search_docs",
            description=(
                "Search Ceph documentation by keyword or concept.\n\n"
                "Use this to find documentation about any Ceph topic — configuration,\n"
                "operations, troubleshooting, architecture, etc. Supports component-scoped\n"
                "search for faster, more relevant results. Uses two-tier search:\n"
                "BM25 keyword match for exact terms, semantic search for conceptual queries.\n"
                "Results are ranked by relevance and documentation quality.\n\n"
                "Args:\n"
                "    query: Natural language query or keywords, e.g. 'how to set up erasure coding'\n"
                "    component: Optional component to scope search (rados, cephfs, rbd, radosgw,\n"
                "        cephadm, mgr, mon, install, start). Omit for global search.\n"
                "    limit: Maximum number of results to return (default 10)\n"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language query or keywords"},
                    "component": {
                        "type": "string",
                        "description": "Ceph component to scope search (e.g. rados, cephfs, rbd, radosgw, cephadm)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="search_examples",
            description=(
                "Search code examples and config snippets from Ceph documentation.\n\n"
                "Use this when you need actual command examples, configuration snippets,\n"
                "or code samples. Returns code blocks with their surrounding context\n"
                "and detected Ceph commands. Can filter by language (bash, yaml, json, python).\n\n"
                "Args:\n"
                "    query: What kind of example you're looking for, e.g. 'create erasure coded pool'\n"
                "    component: Optional component scope (e.g. 'rados', 'rbd', 'cephadm')\n"
                "    language: Optional language filter (e.g. 'bash', 'yaml', 'json', 'python')\n"
                "    limit: Maximum number of results to return (default 10)\n"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What kind of example to find"},
                    "component": {
                        "type": "string",
                        "description": "Ceph component to scope search (e.g. rados, rbd, cephadm)",
                    },
                    "language": {
                        "type": "string",
                        "description": "Filter by language (e.g. bash, yaml, json, python)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_doc_page",
            description=(
                "Get the full content of a Ceph documentation page by its source path.\n\n"
                "Use this when you already know which doc page you need (e.g. from a\n"
                "search result's source_file field) and want to read the complete content.\n"
                "Returns all sections from that page with their metadata.\n\n"
                "Args:\n"
                "    source_file: RST source path relative to doc/, e.g. 'rados/operations/pools.rst'\n"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source_file": {
                        "type": "string",
                        "description": "RST source path (e.g. 'rados/operations/pools.rst')",
                    },
                },
                "required": ["source_file"],
            },
        ),
        Tool(
            name="find_docs_for_command",
            description=(
                "Find documentation pages that reference a specific Ceph CLI command.\n\n"
                "Use this for instant command-to-documentation lookup. No vector search\n"
                "needed — uses a pre-built cross-reference index for sub-millisecond results.\n"
                "Works with any ceph/rbd/rados/cephadm/radosgw-admin command.\n\n"
                "Args:\n"
                "    command: The Ceph command to look up, e.g. 'ceph osd pool create',\n"
                "        'rbd mirror pool enable', 'radosgw-admin user create'\n"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Ceph command (e.g. 'ceph osd pool create', 'rbd mirror pool enable')",
                    },
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="list_components",
            description=(
                "List all available Ceph documentation components with their chunk and example counts.\n\n"
                "Use this to discover what documentation is indexed and decide which\n"
                "component to scope your search to. Returns component names, chunk counts,\n"
                "code example counts, and topic counts.\n"
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="list_topics",
            description=(
                "List topics within a specific Ceph documentation component.\n\n"
                "Use this to understand the structure of a component's documentation\n"
                "before searching. For example, 'rados' has topics like 'operations',\n"
                "'configuration', 'troubleshooting'.\n\n"
                "Args:\n"
                "    component: Component name, e.g. 'rados', 'cephfs', 'rbd', 'radosgw', 'cephadm'\n"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "component": {
                        "type": "string",
                        "description": "Component name (e.g. 'rados', 'cephfs', 'rbd', 'cephadm')",
                    },
                },
                "required": ["component"],
            },
        ),
        Tool(
            name="capabilities",
            description=(
                "Get the capabilities of this documentation knowledge base.\n\n"
                "Returns the entity types indexed, supported operations/tools,\n"
                "and the Ceph version covered. Use this to understand what this\n"
                "MCP server can do.\n"
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="health",
            description=(
                "Get the health status of the documentation index.\n\n"
                "Returns index statistics including total chunks, code examples,\n"
                "per-component counts, embedding model info, build timestamp,\n"
                "and command cross-reference entry count. Use to verify the index\n"
                "is loaded and inspect coverage.\n"
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


class CephDocMCPServer:
    def __init__(self, kb_path: Path, config: dict):
        self.kb_path = kb_path
        self.config = config
        self.metadata: IndexMetadata | None = None
        self.command_xref: dict[str, list[dict]] = {}
        self._router = None

    def _load(self) -> None:
        metadata_file = self.kb_path / "metadata.json"
        if metadata_file.exists():
            self.metadata = IndexMetadata.load(metadata_file)
        self.command_xref = _load_command_xref(self.kb_path)

    def _get_router(self):
        if self._router is None:
            from ceph_doc_kb.search.router import SearchRouter
            self._router = SearchRouter(self.kb_path, self.config)
        return self._router

    def _search_docs(self, query: str, component: str | None, limit: int) -> list[dict]:
        router = self._get_router()
        results = router.search(query, component=component, limit=limit)
        if not results and component:
            results = router.search(query, component=None, limit=limit)
        return [r.to_dict() for r in results]

    def _search_examples(
        self, query: str, component: str | None, language: str | None, limit: int
    ) -> list[dict]:
        router = self._get_router()
        return router.search_code_examples(
            query, component=component, language=language, limit=limit
        )

    def _get_doc_page(self, source_file: str) -> dict:
        router = self._get_router()
        chunks = router.get_chunks_for_source(source_file)
        if chunks:
            sections = [c.to_dict() for c in sorted(chunks, key=lambda c: c.section_path)]
            return {
                "source_file": source_file,
                "sections": sections,
                "section_count": len(sections),
            }
        return {"error": f"No documentation found for source file: {source_file}"}

    def _find_docs_for_command(self, command: str) -> dict:
        normalized = command.strip().lower()

        if normalized in self.command_xref:
            return {"command": command, "references": self.command_xref[normalized]}

        # Prefix match: find all commands that start with the query
        matches: list[dict] = []
        matched_keys: list[str] = []
        seen_chunks: set[str] = set()
        for key, refs in self.command_xref.items():
            if key.startswith(normalized) or normalized.startswith(key):
                matched_keys.append(key)
                for ref in refs:
                    cid = ref.get("chunk_id", "")
                    if cid not in seen_chunks:
                        seen_chunks.add(cid)
                        matches.append(ref)

        return {
            "command": command,
            "matched_keys": matched_keys[:10] if matched_keys else [],
            "references": matches[:20],
        }

    def _list_components(self) -> list[dict]:
        if not self.metadata:
            return []
        return [
            {
                "name": name,
                "chunk_count": comp.chunk_count,
                "code_example_count": comp.code_example_count,
                "topic_count": len(comp.topics),
            }
            for name, comp in self.metadata.components.items()
        ]

    def _list_topics(self, component: str) -> dict:
        if not self.metadata:
            return {"error": "No index loaded"}
        comp = self.metadata.components.get(component)
        if not comp:
            available = list(self.metadata.components.keys())
            return {"error": f"Unknown component: {component}", "available": available}
        return {"component": component, "topics": comp.topics}

    def _capabilities(self) -> dict:
        return {
            "entity_types": ["doc_chunk", "code_example", "command_xref"],
            "operations": [
                "search_docs",
                "search_examples",
                "get_doc_page",
                "find_docs_for_command",
                "list_components",
                "list_topics",
            ],
            "version": self.metadata.version if self.metadata else "unknown",
            "ceph_version": self.metadata.ceph_version if self.metadata else "unknown",
        }

    def _health(self) -> dict:
        if not self.metadata:
            return {"status": "no_index", "message": "No index loaded"}
        return {
            "status": "ok",
            "version": self.metadata.version,
            "ceph_version": self.metadata.ceph_version,
            "embedding_model": self.metadata.embedding_model,
            "embedding_dimensions": self.metadata.embedding_dimensions,
            "total_chunks": self.metadata.total_chunks,
            "total_code_examples": self.metadata.total_code_examples,
            "components": {
                name: {"chunk_count": comp.chunk_count, "code_example_count": comp.code_example_count}
                for name, comp in self.metadata.components.items()
            },
            "build_timestamp": self.metadata.build_timestamp,
            "command_xref_entries": len(self.command_xref),
        }

    def handle_tool_call(self, name: str, arguments: dict) -> str:
        REQUIRED_ARGS = {
            "search_docs": ["query"],
            "search_examples": ["query"],
            "get_doc_page": ["source_file"],
            "find_docs_for_command": ["command"],
            "list_topics": ["component"],
        }

        required = REQUIRED_ARGS.get(name, [])
        missing = [arg for arg in required if arg not in arguments]
        if missing:
            return json.dumps({"error": f"Missing required arguments: {missing}"})

        max_limit = self.config.get("search", {}).get("max_limit", 50)

        handlers = {
            "search_docs": lambda: self._search_docs(
                arguments["query"],
                arguments.get("component"),
                min(arguments.get("limit", 10), max_limit),
            ),
            "search_examples": lambda: self._search_examples(
                arguments["query"],
                arguments.get("component"),
                arguments.get("language"),
                min(arguments.get("limit", 10), max_limit),
            ),
            "get_doc_page": lambda: self._get_doc_page(arguments["source_file"]),
            "find_docs_for_command": lambda: self._find_docs_for_command(arguments["command"]),
            "list_components": lambda: self._list_components(),
            "list_topics": lambda: self._list_topics(arguments["component"]),
            "capabilities": lambda: self._capabilities(),
            "health": lambda: self._health(),
        }
        handler = handlers.get(name)
        if not handler:
            return json.dumps({"error": f"Unknown tool: {name}"})
        try:
            result = handler()
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.exception("Tool call %s failed", name)
            return json.dumps({"error": str(e)})


def create_server(kb_path: str | None = None, version: str | None = None) -> Server:
    config = _load_config()
    resolved_path = _resolve_kb_path(kb_path, version)
    doc_server = CephDocMCPServer(resolved_path, config)
    doc_server._load()

    server = Server("ceph-doc-kb")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return _build_tools()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        result = doc_server.handle_tool_call(name, arguments)
        return [TextContent(type="text", text=result)]

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Ceph Documentation KB — MCP Server")
    parser.add_argument(
        "--kb-path",
        type=str,
        default=None,
        help="Path to knowledge base directory (default: knowledge/ relative to project root)",
    )
    parser.add_argument(
        "--version",
        type=str,
        default=None,
        help="Index version to load (default: latest)",
    )
    args = parser.parse_args()

    server = create_server(kb_path=args.kb_path, version=args.version)

    async def _run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
