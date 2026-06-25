# Development Guide — ceph-doc-kb

## Architecture

The system has two distinct phases:

```
┌─────────────────────────────────────────────────────────┐
│                    INDEXING PHASE                         │
│  (offline, run by maintainer when Ceph releases)         │
│                                                          │
│  RST Files → Parser → Scorer → Embedder → FAISS Index   │
│                  ↓         ↓                             │
│           Code Extractor  XRef Builder                   │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼ knowledge/ directory
┌─────────────────────────────────────────────────────────┐
│                    SERVING PHASE                          │
│  (runtime, MCP server or REST API)                       │
│                                                          │
│  Query → BM25 Search → Semantic Search → Re-rank        │
│                                                          │
│  MCP Server (stdio) / REST API (HTTP)                    │
└─────────────────────────────────────────────────────────┘
```

## Source Tree

```
ceph-doc-kb/
├── pyproject.toml              # Package config, dependencies
├── config.yaml                 # Search weights, embedding model, server config
├── index_docs.py               # CLI: full/incremental index builds
│
├── src/ceph_doc_kb/
│   ├── __init__.py
│   ├── models.py               # DocChunk, CodeExample, IndexMetadata, SearchResult
│   ├── constants.py            # Shared regex, tokenizer, stopwords
│   │
│   ├── indexer/
│   │   ├── parser.py           # RST → DocChunks (docutils, directive handling)
│   │   ├── scorer.py           # Quality scoring (code, commands, length)
│   │   ├── code_extractor.py   # Code block extraction + command detection
│   │   ├── xref.py             # Command → doc cross-reference builder
│   │   ├── embedder.py         # fastembed ONNX + FAISS index builder
│   │   ├── builder.py          # Full pipeline orchestrator
│   │   └── incremental.py      # Git-diff based incremental updates
│   │
│   ├── search/
│   │   ├── keyword_search.py   # Tier 1: BM25 (rank-bm25)
│   │   ├── semantic_search.py  # Tier 2: fastembed + FAISS
│   │   └── router.py           # Two-tier merge + quality re-ranking
│   │
│   └── server/
│       ├── mcp_server.py       # MCP server (8 tools, stdio transport)
│       └── rest_api.py         # REST API (Starlette, 8 endpoints)
│
├── tests/
│   ├── fixtures/               # Sample RST files
│   ├── test_parser.py
│   ├── test_code_extractor.py
│   ├── test_scorer.py
│   ├── test_search.py
│   └── test_mcp_server.py
│
├── knowledge/                  # Built indices (gitignored)
│   └── doc-20.2.1/
│       ├── metadata.json
│       ├── command_xref.json
│       ├── rados/
│       │   ├── faiss.index
│       │   ├── chunks.json
│       │   └── code_examples.json
│       ├── cephfs/
│       ├── rbd/
│       └── ...
│
├── vscode-extension/           # VS Code extension
├── examples/                   # Integration examples
├── SPEC.md                     # MCP contract documentation
├── DEVELOPMENT.md              # This file
├── BOB_INTEGRATION_GUIDE.md    # Agent integration guide
└── .cursor/rules/              # Cursor AI rules
```

## Knowledge Base On-Disk Layout

```
knowledge/doc-{version}/
├── metadata.json           # IndexMetadata: version, model, stats, components
├── command_xref.json       # {command: [{chunk_id, title, source, component}]}
├── {component}/
│   ├── faiss.index         # FAISS IndexFlatIP (cosine on L2-normalized vectors)
│   ├── chunks.json         # [{entity_id, title, content, ...}]
│   └── code_examples.json  # [{entity_id, code, language, context, ...}]
```

## REST API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/search?query=...&component=...&limit=10` | Search documentation |
| GET | `/api/examples?query=...&component=...&language=...&limit=10` | Search code examples |
| GET | `/api/doc/{source_file:path}` | Get full doc page |
| GET | `/api/command/{command:path}` | Find docs for command |
| GET | `/api/components` | List all components |
| GET | `/api/components/{component}/topics` | List topics in component |
| GET | `/api/health` | Health check + stats |
| GET | `/api/capabilities` | Server capabilities |

Start the server:

```bash
python3 -m ceph_doc_kb.server.rest_api
# Binds to 127.0.0.1:8100 (configurable in config.yaml)
```

## MCP Tools

| Tool | Arguments | Description |
|------|-----------|-------------|
| `search_docs` | query, component?, limit? | Two-tier search (BM25 + semantic) |
| `search_examples` | query, component?, language?, limit? | Code example search |
| `get_doc_page` | source_file | Full page content |
| `find_docs_for_command` | command | Instant command→doc lookup |
| `list_components` | — | Component list with counts |
| `list_topics` | component | Topics within component |
| `capabilities` | — | Server capabilities |
| `health` | — | Index status |

## Building the Index

### Full Build (new Ceph release)

```bash
# 1. Get Ceph docs via sparse checkout
git clone --depth 1 --branch v20.2.1 --sparse https://github.com/ceph/ceph.git /tmp/ceph-docs
cd /tmp/ceph-docs && git sparse-checkout set doc

# 2. Build the index
cd /path/to/ceph-doc-kb
python3 index_docs.py --docs-path /tmp/ceph-docs/doc --version 20.2.1 --verbose
```

### Incremental Update (patch release)

```bash
python3 index_docs.py --update \
    --docs-path /tmp/ceph-docs/doc \
    --repo-path /tmp/ceph-docs \
    --from-version v20.2.1 --to-version v20.2.2
```

### Adding a New Ceph Version

1. Sparse-clone the new tag
2. Run `index_docs.py` with the new `--version`
3. The new index is stored alongside existing ones in `knowledge/`
4. The server auto-selects the latest version

## Running Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Key Design Decisions

- **Per-component indices** — faster search, better relevance than one flat index
- **Two-tier search** — BM25 for exact keyword hits, semantic for conceptual queries
- **Quality scoring** — chunks with code + explanation rank higher than ToC/stubs
- **fastembed (ONNX)** — ~100MB total, no PyTorch dependency, CPU-optimized
- **Command cross-reference** — instant O(1) lookup from any command to its docs
- **RST directive awareness** — deprecated/versionadded/warning metadata preserved
- **Incremental updates** — git diff between tags, re-index only changed files

## Dependencies

| Package | Purpose | Size |
|---------|---------|------|
| fastembed | ONNX embeddings (BAAI/bge-small-en-v1.5) | ~100MB |
| faiss-cpu | Vector similarity search | ~30MB |
| rank-bm25 | BM25 keyword search | ~50KB |
| docutils | RST parsing | ~2MB |
| mcp | MCP server protocol | ~100KB |
| starlette + uvicorn | REST API | ~2MB |
