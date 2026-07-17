"""MCP server exposing Ceph documentation knowledge base tools."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

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


def _discover_all_kb_paths(kb_path: str | None) -> list[Path]:
    """Discover all versioned knowledge bases (upstream + IBM)."""
    base = Path(kb_path) if kb_path else PROJECT_ROOT / "knowledge"
    if not base.exists():
        return []
    paths = sorted(
        [d for d in base.iterdir() if d.is_dir() and (d / "metadata.json").exists()],
        key=_version_sort_key,
    )
    return paths


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
                "IMPORTANT: This KB contains multiple versions (upstream Ceph + IBM Storage Ceph\n"
                "8.0, 8.1, 9.0, 9.1). If the user hasn't specified which version they need,\n"
                "ASK them before searching. Use list_versions to see available versions.\n\n"
                "Args:\n"
                "    query: Natural language query or keywords, e.g. 'how to set up erasure coding'\n"
                "    component: Optional component to scope search (rados, cephfs, rbd, radosgw,\n"
                "        cephadm, mgr, mon, install, start). Omit for global search.\n"
                "    version: Optional version filter. Use 'ibm-8.0', 'ibm-8.1', 'ibm-9.0',\n"
                "        'ibm-9.1' for IBM docs, or 'upstream' for upstream Ceph docs.\n"
                "        Omit to search all versions.\n"
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
                    "version": {
                        "type": "string",
                        "description": "Version filter: 'ibm-8.0', 'ibm-8.1', 'ibm-9.0', 'ibm-9.1', or 'upstream'. Omit for all.",
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
                "IMPORTANT: If the user hasn't specified which Ceph version they need,\n"
                "ASK them before searching. Use list_versions to see available versions.\n\n"
                "Args:\n"
                "    query: What kind of example you're looking for, e.g. 'create erasure coded pool'\n"
                "    component: Optional component scope (e.g. 'rados', 'rbd', 'cephadm')\n"
                "    version: Optional version filter: 'ibm-8.0', 'ibm-8.1', 'ibm-9.0',\n"
                "        'ibm-9.1', or 'upstream'. Omit to search all.\n"
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
                    "version": {
                        "type": "string",
                        "description": "Version filter: 'ibm-8.0', 'ibm-8.1', 'ibm-9.0', 'ibm-9.1', or 'upstream'. Omit for all.",
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
                "        or IBM docs path like 'ibm-docs/8.1/installing'\n"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source_file": {
                        "type": "string",
                        "description": "Source path (e.g. 'rados/operations/pools.rst' or 'ibm-docs/8.1/topic-slug')",
                    },
                },
                "required": ["source_file"],
            },
        ),
        Tool(
            name="get_doc_chunk",
            description=(
                "Get the full content of a specific documentation chunk by its entity ID.\n\n"
                "Use this after find_docs_for_command or search_docs when you have a\n"
                "chunk_id/entity_id and want to read that specific section's full content\n"
                "without fetching the entire page. Returns the chunk's title, full text,\n"
                "component, source file, and referenced commands.\n\n"
                "Args:\n"
                "    entity_id: The chunk's 16-character hex entity ID (from search results\n"
                "        or find_docs_for_command references)\n"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "description": "16-char hex chunk ID (e.g. from find_docs_for_command results)",
                    },
                },
                "required": ["entity_id"],
            },
        ),
        Tool(
            name="find_docs_for_command",
            description=(
                "Find documentation pages that reference a specific Ceph CLI command.\n\n"
                "Use this for instant command-to-documentation lookup. No vector search\n"
                "needed — uses a pre-built cross-reference index for sub-millisecond results.\n"
                "Works with any ceph/rbd/rados/cephadm/radosgw-admin command.\n\n"
                "IMPORTANT: If the user hasn't specified which Ceph version they need,\n"
                "ASK them before searching. Use list_versions to see available versions.\n\n"
                "Args:\n"
                "    command: The Ceph command to look up, e.g. 'ceph osd pool create',\n"
                "        'rbd mirror pool enable', 'radosgw-admin user create'\n"
                "    version: Optional version filter: 'ibm-8.0', 'ibm-8.1', 'ibm-9.0',\n"
                "        'ibm-9.1', or 'upstream'. Omit to search all.\n"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Ceph command (e.g. 'ceph osd pool create', 'rbd mirror pool enable')",
                    },
                    "version": {
                        "type": "string",
                        "description": "Version filter: 'ibm-8.0', 'ibm-8.1', 'ibm-9.0', 'ibm-9.1', or 'upstream'. Omit for all.",
                    },
                },
                "required": ["command"],
            },
        ),
        Tool(
            name="list_versions",
            description=(
                "List all available documentation versions in this knowledge base.\n\n"
                "IMPORTANT: Call this tool FIRST when the user asks a doc question without\n"
                "specifying a version. Present the available versions and ask which one\n"
                "they want before searching.\n\n"
                "Returns version identifiers, source type (upstream vs IBM downstream),\n"
                "chunk counts, and upstream Ceph equivalent for each IBM version.\n"
            ),
            inputSchema={"type": "object", "properties": {}},
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
        self._additional_routers: list = []
        self._additional_metadata: list[IndexMetadata] = []
        self._additional_xrefs: list[dict[str, list[dict]]] = []

    def _load(self) -> None:
        metadata_file = self.kb_path / "metadata.json"
        if metadata_file.exists():
            self.metadata = IndexMetadata.load(metadata_file)
        self.command_xref = _load_command_xref(self.kb_path)

    def load_additional_kb(self, kb_path: Path) -> None:
        """Load an additional knowledge base (e.g., IBM docs) alongside the primary."""
        metadata_file = kb_path / "metadata.json"
        if not metadata_file.exists():
            logger.warning("No metadata.json in additional KB: %s", kb_path)
            return

        from ceph_doc_kb.search.router import SearchRouter
        try:
            router = SearchRouter(kb_path, self.config)
            metadata = IndexMetadata.load(metadata_file)
            xref = _load_command_xref(kb_path)
            self._additional_routers.append(router)
            self._additional_metadata.append(metadata)
            self._additional_xrefs.append(xref)
            # Merge command xref into the main one
            for cmd, refs in xref.items():
                if cmd in self.command_xref:
                    self.command_xref[cmd].extend(refs)
                else:
                    self.command_xref[cmd] = list(refs)
            logger.info(
                "Loaded additional KB: %s (%s, %d chunks)",
                kb_path.name, metadata.ceph_version, metadata.total_chunks,
            )
        except Exception:
            logger.exception("Failed to load additional KB: %s", kb_path)

    def _get_router(self):
        if self._router is None:
            from ceph_doc_kb.search.router import SearchRouter
            self._router = SearchRouter(self.kb_path, self.config)
        return self._router

    def _search_docs(self, query: str, component: str | None, limit: int, version: str | None = None) -> list[dict]:
        router = self._get_router()
        results = router.search(query, component=component, limit=limit)
        if not results and component:
            results = router.search(query, component=None, limit=limit)

        # Search additional KBs (IBM docs) and merge
        for extra_router in self._additional_routers:
            extra_results = extra_router.search(query, component=component, limit=limit)
            if not extra_results and component:
                extra_results = extra_router.search(query, component=None, limit=limit)
            results.extend(extra_results)

        # Deduplicate and re-sort by score
        seen: dict[str, Any] = {}
        for r in results:
            eid = r.chunk.entity_id
            if eid not in seen or r.score > seen[eid].score:
                seen[eid] = r
        merged = sorted(seen.values(), key=lambda r: r.score, reverse=True)

        # Apply version filter
        if version:
            merged = self._filter_by_version(merged, version)

        return [r.to_dict() for r in merged[:limit]]

    def _search_examples(
        self, query: str, component: str | None, language: str | None, limit: int, version: str | None = None
    ) -> list[dict]:
        router = self._get_router()
        results = router.search_code_examples(
            query, component=component, language=language, limit=limit
        )
        # Search additional KBs
        for extra_router in self._additional_routers:
            extra = extra_router.search_code_examples(
                query, component=component, language=language, limit=limit
            )
            results.extend(extra)

        # Apply version filter
        if version:
            results = [
                r for r in results
                if self._matches_version(r.get("source_file", ""), version)
            ]

        return results[:limit]

    def _get_doc_page(self, source_file: str) -> dict:
        router = self._get_router()
        chunks = router.get_chunks_for_source(source_file)
        # Also search additional KBs
        if not chunks:
            for extra_router in self._additional_routers:
                chunks = extra_router.get_chunks_for_source(source_file)
                if chunks:
                    break
        if chunks:
            sections = [c.to_dict() for c in sorted(chunks, key=lambda c: c.section_path)]
            return {
                "source_file": source_file,
                "sections": sections,
                "section_count": len(sections),
            }
        return {"error": f"No documentation found for source file: {source_file}"}

    def _get_doc_chunk(self, entity_id: str) -> dict:
        router = self._get_router()
        for chunks in router._chunks_by_component.values():
            for chunk in chunks:
                if chunk.entity_id == entity_id:
                    return chunk.to_dict()
        # Search additional KBs
        for extra_router in self._additional_routers:
            for chunks in extra_router._chunks_by_component.values():
                for chunk in chunks:
                    if chunk.entity_id == entity_id:
                        return chunk.to_dict()
        return {"error": f"Chunk not found: {entity_id}"}

    def _find_docs_for_command(self, command: str, version: str | None = None) -> dict:
        normalized = command.strip().lower()

        if normalized in self.command_xref:
            refs = self.command_xref[normalized]
        else:
            # Prefix match: find all commands that start with the query
            refs = []
            matched_keys: list[str] = []
            seen_chunks: set[str] = set()
            for key, key_refs in self.command_xref.items():
                if key.startswith(normalized) or normalized.startswith(key):
                    matched_keys.append(key)
                    for ref in key_refs:
                        cid = ref.get("chunk_id", "")
                        if cid not in seen_chunks:
                            seen_chunks.add(cid)
                            refs.append(ref)

        # Apply version filter
        if version:
            refs = [
                r for r in refs
                if self._matches_version(r.get("source", ""), version)
            ]

        result: dict[str, Any] = {"command": command, "references": refs[:20]}
        if not (normalized in self.command_xref):
            result["matched_keys"] = matched_keys[:10] if 'matched_keys' in dir() else []
        return result

    @staticmethod
    def _matches_version(source_file: str, version: str) -> bool:
        """Check if a source_file matches the requested version filter."""
        version_lower = version.lower().strip()
        if version_lower == "upstream":
            return "ibm-docs/" not in source_file
        if version_lower.startswith("ibm-"):
            # e.g. "ibm-8.1" should match source files like "ibm-docs/8.1/..."
            ver_num = version_lower.replace("ibm-", "")
            return f"ibm-docs/{ver_num}/" in source_file
        # Also accept bare version numbers like "8.1"
        if version_lower.replace(".", "").isdigit():
            return f"ibm-docs/{version_lower}/" in source_file
        return True

    @staticmethod
    def _filter_by_version(results: list, version: str) -> list:
        """Filter SearchResult objects by version."""
        return [
            r for r in results
            if CephDocMCPServer._matches_version(r.chunk.source_file, version)
        ]

    def _list_versions(self) -> list[dict]:
        """List all available documentation versions."""
        versions = []
        if self.metadata:
            versions.append({
                "version_id": "upstream",
                "label": f"Upstream Ceph ({self.metadata.ceph_version})",
                "type": "upstream",
                "ceph_version": self.metadata.ceph_version,
                "total_chunks": self.metadata.total_chunks,
                "total_code_examples": self.metadata.total_code_examples,
            })
        for meta in self._additional_metadata:
            ver = meta.ceph_version
            versions.append({
                "version_id": ver,
                "label": f"IBM Storage Ceph {ver.replace('ibm-', '')}",
                "type": "ibm-downstream",
                "ceph_version": ver,
                "total_chunks": meta.total_chunks,
                "total_code_examples": meta.total_code_examples,
            })
        return versions

    def _list_components(self) -> list[dict]:
        components: dict[str, dict] = {}
        if self.metadata:
            for name, comp in self.metadata.components.items():
                components[name] = {
                    "name": name,
                    "chunk_count": comp.chunk_count,
                    "code_example_count": comp.code_example_count,
                    "topic_count": len(comp.topics),
                    "sources": ["upstream"],
                }
        for meta in self._additional_metadata:
            for name, comp in meta.components.items():
                if name in components:
                    components[name]["chunk_count"] += comp.chunk_count
                    components[name]["code_example_count"] += comp.code_example_count
                    components[name]["sources"].append(meta.ceph_version)
                else:
                    components[name] = {
                        "name": name,
                        "chunk_count": comp.chunk_count,
                        "code_example_count": comp.code_example_count,
                        "topic_count": len(comp.topics),
                        "sources": [meta.ceph_version],
                    }
        return list(components.values())

    def _list_topics(self, component: str) -> dict:
        if not self.metadata and not self._additional_metadata:
            return {"error": "No index loaded"}
        topics: list[str] = []
        found = False
        if self.metadata:
            comp = self.metadata.components.get(component)
            if comp:
                topics.extend(comp.topics)
                found = True
        for meta in self._additional_metadata:
            comp = meta.components.get(component)
            if comp:
                topics.extend(comp.topics)
                found = True
        if not found:
            available = set()
            if self.metadata:
                available.update(self.metadata.components.keys())
            for meta in self._additional_metadata:
                available.update(meta.components.keys())
            return {"error": f"Unknown component: {component}", "available": sorted(available)}
        return {"component": component, "topics": sorted(set(topics))}

    def _capabilities(self) -> dict:
        versions = []
        if self.metadata:
            versions.append(self.metadata.ceph_version)
        for meta in self._additional_metadata:
            versions.append(meta.ceph_version)
        return {
            "entity_types": ["doc_chunk", "code_example", "command_xref"],
            "operations": [
                "search_docs",
                "search_examples",
                "get_doc_page",
                "get_doc_chunk",
                "find_docs_for_command",
                "list_components",
                "list_topics",
            ],
            "sources": ["upstream (ceph.io)", "ibm-downstream (ibm.com/docs)"],
            "versions": versions,
        }

    def _health(self) -> dict:
        if not self.metadata and not self._additional_metadata:
            return {"status": "no_index", "message": "No index loaded"}

        health: dict = {"status": "ok", "knowledge_bases": []}

        if self.metadata:
            health["knowledge_bases"].append({
                "type": "upstream",
                "ceph_version": self.metadata.ceph_version,
                "total_chunks": self.metadata.total_chunks,
                "total_code_examples": self.metadata.total_code_examples,
                "embedding_model": self.metadata.embedding_model,
                "build_timestamp": self.metadata.build_timestamp,
                "components": len(self.metadata.components),
            })

        for meta in self._additional_metadata:
            health["knowledge_bases"].append({
                "type": "ibm-downstream",
                "ceph_version": meta.ceph_version,
                "total_chunks": meta.total_chunks,
                "total_code_examples": meta.total_code_examples,
                "embedding_model": meta.embedding_model,
                "build_timestamp": meta.build_timestamp,
                "components": len(meta.components),
            })

        total_chunks = sum(kb["total_chunks"] for kb in health["knowledge_bases"])
        total_examples = sum(kb["total_code_examples"] for kb in health["knowledge_bases"])
        health["total_chunks"] = total_chunks
        health["total_code_examples"] = total_examples
        health["command_xref_entries"] = len(self.command_xref)

        return health

    def handle_tool_call(self, name: str, arguments: dict) -> str:
        REQUIRED_ARGS = {
            "search_docs": ["query"],
            "search_examples": ["query"],
            "get_doc_page": ["source_file"],
            "get_doc_chunk": ["entity_id"],
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
                max(1, min(arguments.get("limit", 10), max_limit)),
                version=arguments.get("version"),
            ),
            "search_examples": lambda: self._search_examples(
                arguments["query"],
                arguments.get("component"),
                arguments.get("language"),
                max(1, min(arguments.get("limit", 10), max_limit)),
                version=arguments.get("version"),
            ),
            "get_doc_page": lambda: self._get_doc_page(arguments["source_file"]),
            "get_doc_chunk": lambda: self._get_doc_chunk(arguments["entity_id"]),
            "find_docs_for_command": lambda: self._find_docs_for_command(
                arguments["command"],
                version=arguments.get("version"),
            ),
            "list_versions": lambda: self._list_versions(),
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


def create_server(
    kb_path: str | None = None, version: str | None = None,
) -> tuple[Server, CephDocMCPServer]:
    """Create and return the MCP ``Server`` and the backing ``CephDocMCPServer``.

    Automatically discovers and loads all knowledge bases found under the
    knowledge/ directory, including both upstream Ceph docs and IBM downstream docs.
    """
    config = _load_config()
    resolved_path = _resolve_kb_path(kb_path, version)
    doc_server = CephDocMCPServer(resolved_path, config)
    doc_server._load()

    # Auto-discover and load additional KBs (IBM docs, other versions)
    all_kbs = _discover_all_kb_paths(kb_path)
    for kb in all_kbs:
        if kb.resolve() == resolved_path.resolve():
            continue
        doc_server.load_additional_kb(kb)

    from mcp.types import Icon

    ceph_icon = Icon(
        src="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA0OCA0OCIgd2lkdGg9IjQ4IiBoZWlnaHQ9IjQ4Ij48Y2lyY2xlIGN4PSIyNCIgY3k9IjI0IiByPSIyMiIgZmlsbD0iI0VGNTAzQSIvPjx0ZXh0IHg9IjI0IiB5PSIzMiIgZm9udC1mYW1pbHk9IkFyaWFsLHNhbnMtc2VyaWYiIGZvbnQtc2l6ZT0iMjAiIGZvbnQtd2VpZ2h0PSJib2xkIiBmaWxsPSJ3aGl0ZSIgdGV4dC1hbmNob3I9Im1pZGRsZSI+RDwvdGV4dD48L3N2Zz4=",
        mimeType="image/svg+xml",
    )

    server = Server(
        "ceph-doc-kb",
        instructions=(
            "Ceph documentation knowledge base with semantic search. "
            "Includes both upstream Ceph docs and IBM Storage Ceph (downstream) docs. "
            "Use this MCP when you need to find Ceph documentation, "
            "look up how-to guides, find code examples, or get explanations "
            "of Ceph concepts. Searches across all Ceph doc components: "
            "rados, rbd, rgw, cephfs, cephadm, and more. "
            "IBM docs cover IBM-specific procedures (registry, licensing, upgrades). "
            "Key tools: search_docs, search_examples, find_docs_for_command, list_components."
        ),
        icons=[ceph_icon],
    )

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return _build_tools()

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        result = doc_server.handle_tool_call(name, arguments)
        return [TextContent(type="text", text=result)]

    return server, doc_server


def _silence_stderr_logging() -> None:
    """Suppress all logging to stderr for stdio transport.

    Cursor classifies any stderr output as [error] in the MCP output panel,
    making the server appear broken even when healthy.
    """
    logging.disable(logging.CRITICAL)
    import warnings
    warnings.filterwarnings("ignore")


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
    parser.add_argument(
        "--auto-update",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto-pull latest changes from git on startup (default: enabled)",
    )
    parser.add_argument(
        "--update-interval",
        type=float,
        default=1,
        metavar="HOURS",
        help="Hours between periodic update checks (default: 1, 0=disable periodic)",
    )
    args = parser.parse_args()

    _silence_stderr_logging()

    server, doc_server = create_server(kb_path=args.kb_path, version=args.version)

    if args.auto_update:
        from ceph_doc_kb.server.auto_update import start_auto_update
        start_auto_update(doc_server, update_interval_hours=args.update_interval)

    async def _run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
