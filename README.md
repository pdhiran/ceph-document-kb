# ceph-doc-kb

Version-aware, component-scoped Ceph documentation knowledge base. Indexes Ceph RST docs into per-component vector indices with two-tier search (BM25 + semantic via fastembed/FAISS).

## Quick Start

```bash
# Install
pip install -e .

# Build index from Ceph docs
git clone --depth 1 --branch v20.2.1 --sparse https://github.com/ceph/ceph.git /tmp/ceph-docs
cd /tmp/ceph-docs && git sparse-checkout set doc
cd /path/to/ceph-doc-kb
python3 index_docs.py --docs-path /tmp/ceph-docs/doc --version 20.2.1 --verbose
```

## Architecture

- **Component-scoped indices**: Each Ceph component (rados, rbd, rgw, cephfs, cephadm) gets its own FAISS index for fast, targeted search
- **Two-tier search**: BM25 keyword match for exact terms, fastembed semantic search for conceptual queries
- **Command cross-reference**: Instant lookup from any `ceph`/`rbd`/`rados` command to relevant docs
- **Quality scoring**: Chunks with code examples, commands, and explanations rank higher
- **Version-aware**: Supports multiple Ceph release indices side by side

## Connect Your Agent

**Cursor** — add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "ceph-doc-kb": {
      "command": "python3",
      "args": ["-m", "ceph_doc_kb.server.mcp_server"],
      "cwd": "/path/to/ceph-doc-kb"
    }
  }
}
```

---

**Claude Desktop** — start the server, then add to `claude_desktop_config.json`:

```bash
python -m ceph_doc_kb.server.mcp_server --transport sse --port 8082
```

```json
{
  "mcpServers": {
    "ceph-doc-kb": { "url": "http://localhost:8082/sse" }
  }
}
```

---

**Continue / Cline / Windsurf** — start the server and point to the SSE endpoint:

```bash
python -m ceph_doc_kb.server.mcp_server --transport sse --port 8082
```

Connect to `http://localhost:8082/sse` in the tool's MCP settings.

---

**IBM Bob** — Bob supports MCP over SSE natively:

```bash
python -m ceph_doc_kb.server.mcp_server --transport sse --host 0.0.0.0 --port 8082
```

Add to Bob's `.bob/mcp.json`:

```json
{
  "mcpServers": {
    "ceph-doc-kb": {
      "url": "http://localhost:8082/sse",
      "transport": "sse"
    }
  }
}
```

If running on a shared server, replace `localhost` with the hostname.

---

**LangChain / CrewAI / CI pipelines** — use the REST API:

```bash
python -m ceph_doc_kb.server.rest_api --host 0.0.0.0 --port 8100
```

### Tools

| Tool | Description |
|------|-------------|
| `search_docs` | Search docs with optional component scoping |
| `search_examples` | Search code examples and configs |
| `get_doc_page` | Get full doc page content |
| `find_docs_for_command` | Instant command-to-doc lookup |
| `list_components` | List available components |
| `list_topics` | List topics within a component |
| `capabilities` | Server capabilities |
| `health` | Index health status |

## REST API

```bash
python3 -m ceph_doc_kb.server.rest_api
# http://127.0.0.1:8100/api/search?query=erasure+coding&component=rados
```

See [BOB_INTEGRATION_GUIDE.md](BOB_INTEGRATION_GUIDE.md) for full endpoint reference with curl examples.

## VS Code Extension

A VS Code extension is available for interactive documentation search:

```bash
cd vscode-extension && npm install
# Install via "Developer: Install Extension from Location..."
```

Features: search docs (`Cmd+Alt+D`), search examples (`Cmd+Alt+E`), find docs for command (`Cmd+Alt+F`), insert code at cursor.

See [vscode-extension/README.md](vscode-extension/README.md) for details.

## Agent Integration

Python client for LLM agents (no external dependencies):

```python
from examples.agent_integration import CephDocKBClient

client = CephDocKBClient("http://localhost:8100")
results = client.search_docs("erasure coding", component="rados")
```

LangChain and CrewAI wrappers included. See [BOB_INTEGRATION_GUIDE.md](BOB_INTEGRATION_GUIDE.md).

## Incremental Updates

```bash
python3 index_docs.py --update --docs-path /tmp/ceph-docs/doc \
    --repo-path /tmp/ceph-docs --from-version v20.2.1 --to-version v20.2.2
```

## Documentation

| Document | Description |
|----------|-------------|
| [SPEC.md](SPEC.md) | MCP platform contract and entity schema |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Architecture, source tree, maintainer guide |
| [BOB_INTEGRATION_GUIDE.md](BOB_INTEGRATION_GUIDE.md) | REST API reference, agent integration, deployment |
| [vscode-extension/README.md](vscode-extension/README.md) | VS Code extension install and usage |

## Running All Ceph MCPs Together

Three specialized MCPs work together as the Ceph Engineering Intelligence Platform:

| MCP | Purpose | SSE Port | Repo |
|-----|---------|----------|------|
| **ceph-cmd-kb** | Commands, configs, test validation | 8081 | [ceph-command-kb](https://github.com/pdhiran/ceph-command-kb) |
| **ceph-doc-kb** | Documentation search, code examples | 8082 | [ceph-doc-kb](https://github.com/pdhiran/ceph-document-kb) |
| **ceph-issue-kb** | Known issues, workarounds, fixes | 8083 | [ceph-issue-kb](https://github.com/pdhiran/ceph-issue-kb) |

Start all three for SSE clients (Bob, Claude Desktop, etc.):

```bash
python -m ceph_command_kb.server.mcp_server --transport sse --port 8081 &
python -m ceph_doc_kb.server.mcp_server --transport sse --port 8082 &
python -m ceph_issue_kb.server.mcp_server --transport sse --port 8083 &
```

Combined agent config (`.bob/mcp.json`, `claude_desktop_config.json`, etc.):

```json
{
  "mcpServers": {
    "ceph-cmd-kb": { "url": "http://localhost:8081/sse", "transport": "sse" },
    "ceph-doc-kb": { "url": "http://localhost:8082/sse", "transport": "sse" },
    "ceph-issue-kb": { "url": "http://localhost:8083/sse", "transport": "sse" }
  }
}
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for architecture details and contributing.
