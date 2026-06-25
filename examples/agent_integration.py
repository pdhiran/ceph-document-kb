"""Ready-made Python client for the ceph-doc-kb REST API.

Usage:
    from examples.agent_integration import CephDocKBClient

    client = CephDocKBClient("http://localhost:8100")
    results = client.search_docs("erasure coding", component="rados")
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError


class CephDocKBClient:
    """Client for the ceph-doc-kb REST API. No external dependencies required."""

    def __init__(self, base_url: str = "http://localhost:8100", timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            filtered = {k: v for k, v in params.items() if v is not None}
            if filtered:
                url += "?" + urlencode(filtered)
        req = Request(url)
        with urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read())

    def health(self) -> dict:
        """Check server health and get index stats."""
        return self._get("/api/health")

    def capabilities(self) -> dict:
        """Get server capabilities."""
        return self._get("/api/capabilities")

    def list_components(self) -> list[dict]:
        """List all indexed components with counts."""
        data = self._get("/api/components")
        return data.get("components", [])

    def list_topics(self, component: str) -> list[str]:
        """List topics within a component."""
        data = self._get(f"/api/components/{quote(component, safe='')}/topics")
        return data.get("topics", [])

    def search_docs(
        self,
        query: str,
        component: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Search documentation. Returns ranked results with content."""
        data = self._get("/api/search", {
            "query": query,
            "component": component,
            "limit": limit,
        })
        return data.get("results", [])

    def search_examples(
        self,
        query: str,
        component: str | None = None,
        language: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Search code examples. Can filter by language (bash, yaml, json, python)."""
        data = self._get("/api/examples", {
            "query": query,
            "component": component,
            "language": language,
            "limit": limit,
        })
        return data.get("results", [])

    def find_docs_for_command(self, command: str) -> list[dict]:
        """Find documentation pages referencing a Ceph command."""
        data = self._get(f"/api/command/{quote(command, safe='')}")
        return data.get("references", [])

    def get_doc_page(self, source_file: str) -> dict:
        """Get full content of a documentation page."""
        return self._get(f"/api/doc/{source_file}")

    def is_healthy(self) -> bool:
        """Quick check if the server is reachable and has an index."""
        try:
            h = self.health()
            return h.get("status") == "ok"
        except (URLError, OSError):
            return False


# --- Convenience functions for agent frameworks ---

def make_langchain_tools(base_url: str = "http://localhost:8100"):
    """Create LangChain-compatible tool functions."""
    client = CephDocKBClient(base_url)

    def search_docs(query: str) -> str:
        results = client.search_docs(query, limit=5)
        if not results:
            return "No documentation found."
        parts = []
        for r in results:
            parts.append(f"## {r['title']}\n"
                         f"Source: {r['source_file']}\n"
                         f"URL: {r['doc_url']}\n\n"
                         f"{r['content'][:300]}...")
        return "\n\n---\n\n".join(parts)

    def find_docs_for_command(command: str) -> str:
        refs = client.find_docs_for_command(command)
        if not refs:
            return f"No documentation found for command: {command}"
        lines = [f"Documentation for `{command}`:"]
        for r in refs:
            lines.append(f"- **{r['title']}** ({r['component']}/{r['source']})")
        return "\n".join(lines)

    def search_examples(query: str) -> str:
        examples = client.search_examples(query, language="bash", limit=5)
        if not examples:
            return "No code examples found."
        parts = []
        for ex in examples:
            parts.append(f"```{ex['language']}\n{ex['code']}\n```\n"
                         f"Context: {ex.get('context', 'N/A')}")
        return "\n\n".join(parts)

    return {
        "search_docs": search_docs,
        "find_docs_for_command": find_docs_for_command,
        "search_examples": search_examples,
    }


if __name__ == "__main__":
    client = CephDocKBClient()

    if not client.is_healthy():
        print("ERROR: Cannot connect to ceph-doc-kb REST API at http://localhost:8100")
        print("Start it with: python3 -m ceph_doc_kb.server.rest_api")
        raise SystemExit(1)

    h = client.health()
    print(f"Connected: Ceph {h['ceph_version']}, {h['total_chunks']} chunks, "
          f"{len(h['components'])} components")
    print()

    print("Components:")
    for comp in client.list_components():
        print(f"  {comp['name']}: {comp['chunk_count']} chunks, {comp['code_example_count']} examples")
    print()

    print("Search: 'erasure coding pool' in rados")
    results = client.search_docs("erasure coding pool", component="rados", limit=3)
    for r in results:
        print(f"  [{r['score']:.3f}] {r['title']} ({r['source_file']})")
    print()

    print("Command lookup: 'ceph osd pool create'")
    refs = client.find_docs_for_command("ceph osd pool create")
    for r in refs[:5]:
        print(f"  {r['title']} ({r['component']})")
