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
│  MCP Server (stdio or SSE :8082) / REST API (HTTP :8100) │
└─────────────────────────────────────────────────────────┘
```

## Source Tree

```
ceph-document-kb/
├── pyproject.toml              # Package config, dependencies
├── config.yaml                 # Search weights, embedding model, server config
├── index_docs.py               # CLI: full / tag-delta / --since date merge
├── index_ibm_docs.py           # CLI: IBM HTML crawl + --since hash-diff
├── update_index.sh             # Maintainer wrapper (touches .reload_trigger)
│
├── src/ceph_doc_kb/
│   ├── __init__.py
│   ├── models.py               # DocChunk, CodeExample, IndexMetadata, SearchResult
│   ├── constants.py            # Shared regex, tokenizer, IBM_VERSIONS
│   │
│   ├── indexer/
│   │   ├── parser.py           # RST → DocChunks (docutils, directive handling)
│   │   ├── ibm_crawler.py      # IBM docs API crawl
│   │   ├── ibm_parser.py       # IBM HTML → DocChunks
│   │   ├── scorer.py           # Quality scoring (code, commands, length)
│   │   ├── code_extractor.py   # Code block extraction + command detection
│   │   ├── xref.py             # Command → doc cross-reference builder
│   │   ├── embedder.py         # fastembed ONNX + FAISS index builder
│   │   ├── builder.py          # Full pipeline orchestrator
│   │   └── incremental.py      # Tag git-diff + --since git-log merge
│   │
│   ├── search/
│   │   ├── keyword_search.py   # Tier 1: BM25 (rank-bm25)
│   │   ├── semantic_search.py  # Tier 2: fastembed + FAISS
│   │   └── router.py           # Two-tier merge + quality re-ranking
│   │
│   └── server/
│       ├── mcp_server.py       # MCP server (10 tools, stdio or SSE)
│       ├── auto_update.py      # git pull + .reload_trigger watcher
│       └── rest_api.py         # REST API (Starlette, 8 endpoints)
│
├── tests/
│   ├── fixtures/               # Sample RST files
│   ├── test_parser.py
│   ├── test_ibm_parser.py
│   ├── test_code_extractor.py
│   ├── test_scorer.py
│   ├── test_search.py
│   ├── test_incremental.py     # --since date merge + IBM hash-diff
│   ├── test_auto_update.py     # git pull / trigger / update_index.sh
│   └── test_mcp_server.py
│
├── knowledge/                  # Built indices (committed so MCP auto-update can ship them)
│   ├── doc-20.2.1/             # Upstream RST
│   └── doc-ibm-{8.0,8.1,9.0,9.1}/
│
├── vscode-extension/           # VS Code extension
├── examples/                   # Integration examples
├── SPEC.md                     # MCP contract documentation
├── UPDATING.md                 # Maintainer rebuild / --since / hot-reload
├── DEVELOPMENT.md              # This file
├── BOB_INTEGRATION_GUIDE.md    # Agent integration guide
└── .cursor/rules/              # Cursor AI rules
```

## Knowledge Base On-Disk Layout

```
knowledge/doc-{version}/            # upstream, e.g. doc-20.2.1
knowledge/doc-ibm-{version}/        # IBM HTML, e.g. doc-ibm-9.1
    metadata.json                   # IndexMetadata + last_incremental_since
    command_xref.json
    ibm_crawl_metadata.json         # IBM only: updated_since
    {component}/
        faiss.index
        chunks.json
        code_examples.json
```

The MCP loads the numerically latest `knowledge/doc-*/` as primary and every sibling with `metadata.json` as additional (IBM). `reload_from_disk()` rediscovers those siblings after `git pull` or `.reload_trigger`.

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
| `search_docs` | query, component?, version?, limit? | Two-tier search (BM25 + semantic) |
| `search_examples` | query, component?, version?, language?, limit? | Code example search |
| `get_doc_page` | source_file | Full page content |
| `get_doc_chunk` | entity_id | One section by 16-char hex id |
| `find_docs_for_command` | command, version? | Instant command→doc lookup |
| `list_versions` | — | Upstream + IBM indices loaded |
| `list_components` | — | Component list with counts |
| `list_topics` | component | Topics within a component |
| `capabilities` | — | Server capabilities |
| `health` | — | Index status |

SSE: `python3 -m ceph_doc_kb.server.mcp_server --transport sse --port 8082`. `--no-auto-update` disables git pull and the `.reload_trigger` watcher. See [UPDATING.md](UPDATING.md).

## Building the Index

### Full Build (new Ceph release)

```bash
# 1. Get Ceph docs via sparse checkout
git clone --depth 1 --branch v20.2.1 --sparse https://github.com/ceph/ceph.git /tmp/ceph-docs
cd /tmp/ceph-docs && git sparse-checkout set doc

# 2. Build the index
cd /path/to/ceph-document-kb
python3 index_docs.py --docs-path /tmp/ceph-docs/doc --version 20.2.1 --verbose
```

### Incremental update (date delta)

Re-parses RST files from `git log --since` and **merges** into the existing FAISS index. Requires git history (not `--depth 1`) and an existing `knowledge/doc-{version}/`.

```bash
python3 index_docs.py --since 2026-08-01 \
    --docs-path /tmp/ceph-docs/doc \
    --repo-path /tmp/ceph-docs \
    --version 20.2.1 --verbose
```

### Incremental update (patch release tags)

```bash
python3 index_docs.py --update \
    --docs-path /tmp/ceph-docs/doc \
    --repo-path /tmp/ceph-docs \
    --from-version v20.2.1 --to-version v20.2.2
```

### IBM HTML

```bash
python3 index_ibm_docs.py --version 9.1 --since 2026-08-01 \
    --cache-dir ./cache/ibm-9.1 --verbose
```

`--since` recrawls the IBM API and hash-diffs against `--cache-dir`. Unchanged HTML skips the FAISS rebuild. Without `--cache-dir`, `--since` always full-rebuilds. Wrapper: `./update_index.sh` (see [UPDATING.md](UPDATING.md)).

### Adding a New Ceph Version

1. Sparse-clone the new tag (full history if you will use `--since` later)
2. Run `index_docs.py` with the new `--version`
3. The new index is stored alongside existing ones in `knowledge/`
4. The server loads every `knowledge/doc-*/` with `metadata.json` (latest numerically is primary)

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
- **Incremental updates** — git diff between tags, or `git log --since` date merge; IBM `--since` is recrawl + HTML hash-diff

## Dependencies

| Package | Purpose | Size |
|---------|---------|------|
| fastembed | ONNX embeddings (BAAI/bge-small-en-v1.5) | ~100MB |
| faiss-cpu | Vector similarity search | ~30MB |
| rank-bm25 | BM25 keyword search | ~50KB |
| docutils | RST parsing | ~2MB |
| mcp | MCP server protocol | ~100KB |
| starlette + uvicorn | REST API | ~2MB |
