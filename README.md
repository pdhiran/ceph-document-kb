# ceph-doc-kb

Version-aware, component-scoped Ceph **documentation** knowledge base. Indexes upstream RST and IBM Storage Ceph HTML into per-component FAISS indices. Search is two-tier: BM25 keywords + fastembed semantic, then quality re-rank.

Use this MCP for **how-to, architecture, IBM-only procedures, and copy-paste examples**. Use **ceph-cmd-kb** to verify that a command in those docs is still valid for the target release.

## For agents (read this first)

This KB contains **multiple versions**. If the user did not name one, **ask** before searching. `list_versions()` lists what is loaded.

| Version filter | Content |
|----------------|---------|
| `upstream` | Upstream Ceph RST (currently `doc-20.2.1`) |
| `ibm-8.0` | IBM Storage Ceph 8.0 (Reef-era product docs) |
| `ibm-8.1` | IBM Storage Ceph 8.1 |
| `ibm-9.0` | IBM Storage Ceph 9.0 |
| `ibm-9.1` | IBM Storage Ceph 9.1 (Tentacle-era product docs) |

IBM docs cover content that is **not** in upstream: container registry, licensing, crossgrade, staggered upgrade, IBM Dashboard, Call Home, Storage Insights, etc.

| Do | Do not |
|---|---|
| `find_docs_for_command` when the query is a known CLI name (instant xref) | Treat doc examples as verified CLI — still `verify_command` on **ceph-cmd-kb** |
| `search_docs` for conceptual / “how do I” questions | Search here for JIRA/crashes — **ceph-issue-kb** |
| `search_examples` when the user needs a snippet | Scope globally when a component is obvious — pass `component` |
| Pass `version` (`ibm-9.1`, `upstream`, …) | Mix 8.1 IBM procedure with 9.1 CLI without saying so |

**Typical first calls**

1. Ask / infer version → `list_versions()` if unsure.
2. If the user named a command: `find_docs_for_command(command="ceph fs volume create", version="ibm-9.1")`.
3. Else: `search_docs(query="...", component="cephfs", version="ibm-9.1")`.
4. For snippets: `search_examples(query="...", language="bash", component="cephadm")`.
5. `get_doc_page` / `get_doc_chunk` to read the full section.

## Ceph Engineering Intelligence Platform

| MCP | Cursor key | Use when | SSE | REST |
|-----|------------|----------|-----|------|
| **ceph-cmd-kb** | `ceph-cmd-kb` | Verify CLI, flags, configs | 8081 | 9090 |
| **ceph-doc-kb** | `ceph-doc-kb` | How-to, architecture, IBM procedures | 8082 | 8100 |
| **ceph-issue-kb** | `ceph-issue-kb` | Known bugs, workarounds, stacktraces | 8083 | 8200 |
| **ceph-prio-hub** | `ceph-prio-hub` | Customer prio-list / L3 tracking | 8080 | — |
| **cephci-kb** | `cephci-kb` | CephCI code, tests, workflows | 8084 | — |

## Setup

```bash
git clone https://github.com/pdhiran/ceph-document-kb.git
cd ceph-doc-kb
pip install -e .
```

Indices under `knowledge/` are committed so the MCP can serve immediately. Rebuild only when docs change (see [Updating the knowledge base](#updating-the-knowledge-base)).

## Incorporate into an agent

### Cursor (stdio)

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

The server discovers every `knowledge/doc-*/` directory that has `metadata.json` (upstream + IBM) and merges search. Restart Cursor after editing `mcp.json`.

### SSE

```bash
python3 -m ceph_doc_kb.server.mcp_server --transport sse --host 0.0.0.0 --port 8082
```

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

### REST

```bash
python3 -m ceph_doc_kb.server.rest_api --host 0.0.0.0 --port 8100
```

```bash
curl "http://127.0.0.1:8100/api/search?query=erasure+coding&component=rados"
```

Endpoint reference and agent wrappers: [BOB_INTEGRATION_GUIDE.md](BOB_INTEGRATION_GUIDE.md), [examples/agent_integration.py](examples/agent_integration.py). VS Code: [vscode-extension/README.md](vscode-extension/README.md).

## Tool catalog

| Tool | Args | When to call |
|------|------|----------------|
| `search_docs` | `query`, optional `component`, `version`, `limit=10` | Conceptual / keyword search. Scope with `component` when known. |
| `search_examples` | `query`, optional `component`, `version`, `language`, `limit=10` | Code/config snippets. `language`: `bash`, `yaml`, `json`, `python`. |
| `find_docs_for_command` | `command`, optional `version` | Instant command → doc xref (no vector search). |
| `get_doc_page` | `source_file` | Full page text |
| `get_doc_chunk` | `entity_id` (16-char hex from search/xref) | One section, not the whole page |
| `list_versions` | (none) | Upstream + IBM indices loaded |
| `list_components` | (none) | `rados`, `cephfs`, `rbd`, `radosgw`, `cephadm`, `mgr`, … |
| `list_topics` | `component` | Topics inside a component |
| `capabilities` | (none) | Server contract |
| `health` | (none) | Index health |

### Component map

| Component | Topics |
|-----------|--------|
| `rados` | pools, PGs, EC, CRUSH, recovery, OSDs, MONs |
| `rbd` | images, snapshots, mirroring, NVMe, iSCSI |
| `radosgw` / `rgw` | S3/Swift, multisite, users, buckets |
| `cephfs` | MDS, mount, NFS/SMB, quotas, snapshots |
| `cephadm` | bootstrap, services, upgrade, install |
| `mgr` | dashboard, monitoring, Call Home (IBM) |
| `troubleshooting` | IBM troubleshooting books |
| `general` | planning, overview, hardening |

Results include `source_file` so you can tell IBM (`ibm-docs/9.1/...`) from upstream (`rados/operations/pools.rst`).

### Agent workflow: IBM upgrade procedure

1. Confirm IBM version (`8.1` vs `9.1`) → `version="ibm-9.1"`.
2. `search_docs(query="staggered upgrade", component="cephadm", version="ibm-9.1")`
3. `get_doc_page` / `get_doc_chunk` on the best hit.
4. Any CLI in the answer → **ceph-cmd-kb** `verify_command(..., version="tentacle")`.

### Agent workflow: command → docs → verify

1. **ceph-cmd-kb** `verify_command` (existence).
2. `find_docs_for_command` (procedure and caveats).
3. **ceph-issue-kb** `search_issues` if the user is debugging a failure of that command.

## Updating the knowledge base

Same `--since YYYY-MM-DD` contract as `python index_issues.py --since DATE`.

### Upstream RST

Needs a Ceph git checkout with `doc/`. Re-parses only RST files touched since the date and **merges** into the existing FAISS index.

```bash
# First-time full build
git clone --depth 1 --branch v20.2.1 --sparse https://github.com/ceph/ceph.git /tmp/ceph-docs
cd /tmp/ceph-docs && git sparse-checkout set doc
cd /path/to/ceph-doc-kb
python3 index_docs.py --docs-path /tmp/ceph-docs/doc --version 20.2.1 --verbose

# Date delta (git log --since)
python3 index_docs.py --since 2026-08-01 \
    --docs-path /tmp/ceph-docs/doc \
    --repo-path /tmp/ceph-docs \
    --version 20.2.1 --verbose

# Tag-to-tag delta (unchanged)
python3 index_docs.py --update --docs-path /tmp/ceph-docs/doc \
    --repo-path /tmp/ceph-docs --from-version v20.2.1 --to-version v20.2.2
```

Requires an existing `knowledge/doc-{version}/` for `--since`. Deleted RST files drop out of the index.

### IBM HTML

IBM has no git history. `--since` **recrawls** the IBM docs API, hash-compares against `--cache-dir`, and skips the FAISS rebuild when HTML is unchanged. If pages changed, the IBM index is rebuilt from the current snapshot.

```bash
python3 index_ibm_docs.py --version 9.1 --since 2026-08-01 \
    --cache-dir ./cache/ibm-9.1 --verbose

python3 index_ibm_docs.py --version 8.1 --verbose          # full
python3 index_ibm_docs.py --version 8.1 --max-pages 5      # smoke test
```

Supported IBM versions: `8.0`, `8.1`, `9.0`, `9.1` (see `IBM_VERSIONS` in `src/ceph_doc_kb/constants.py`). Output: `knowledge/doc-ibm-{version}/`.

### Maintainer wrapper

```bash
./update_index.sh                 # last run, or last 1 day
./update_index.sh 7
./update_index.sh 2026-08-01
./update_index.sh --reset
```

Environment: `CEPH_DOCS_REPO` (default `/tmp/ceph-docs`), `CEPH_VERSION` (default `20.2.1`), `IBM_VERSIONS` (default `9.1`), `SKIP_UPSTREAM=1`, `SKIP_IBM=1`.

Metadata fields: `last_incremental_since` on `metadata.json`; IBM also writes `updated_since` on `ibm_crawl_metadata.json`.

The MCP auto-pulls this git repo on a timer and hot-reloads every `knowledge/doc-*/` index (Cursor stays open; only a `.py` pull respawns the MCP subprocess). `./update_index.sh` touches `.reload_trigger` for the same in-process reload. `--no-auto-update` disables git pull (the trigger watcher still starts unless that flag is set).

Full maintainer help: [UPDATING.md](UPDATING.md).

## Architecture

```
Upstream RST  → parser → scorer → embedder → knowledge/doc-20.2.1/<component>/
IBM HTML API  → crawler → ibm_parser ──────→ knowledge/doc-ibm-9.1/<component>/
                                              command_xref.json
                                                      │
                                                      ▼
                         search router (BM25 + FAISS + quality rank)
```

See [DEVELOPMENT.md](DEVELOPMENT.md) and [SPEC.md](SPEC.md).

## Development

```bash
pip install -e ".[dev]"
pytest
```
