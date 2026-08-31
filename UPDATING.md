# Updating the documentation knowledge base

This is the maintainer help for **ceph-doc-kb**. Agents and humans: use this page when rebuilding or refreshing the served index. Do not invent a different workflow.

Cursor does **not** need a restart after an index update. The MCP process hot-reloads every `knowledge/doc-*/` directory (upstream + IBM) in-process, or (only if `.py` files changed) Cursor respawns the MCP subprocess.

## Canonical command

```bash
cd /path/to/ceph-doc-kb
./update_index.sh                 # since last successful run, or last 1 day
./update_index.sh 7               # last 7 days
./update_index.sh 2026-08-01      # explicit ISO date
./update_index.sh --reset         # clear .last_index_update
```

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `CEPH_DOCS_REPO` | `/tmp/ceph-docs` | Ceph git checkout containing `doc/` |
| `CEPH_VERSION` | `20.2.1` | Upstream index label (`knowledge/doc-<version>/`) |
| `IBM_VERSIONS` | `9.1` | Space-separated IBM versions to recrawl |
| `SKIP_UPSTREAM=1` | off | Skip RST incremental |
| `SKIP_IBM=1` | off | Skip IBM recrawl |

## What `./update_index.sh` does

1. Resolves `--since`.
2. Upstream: `python3 index_docs.py --since DATE --docs-path $CEPH_DOCS_REPO/doc --repo-path $CEPH_DOCS_REPO --version $CEPH_VERSION`.
3. IBM: `python3 index_ibm_docs.py --version VER --since DATE --cache-dir ./cache/ibm-VER` for each `IBM_VERSIONS` entry.
4. Touches `.reload_trigger`.
5. Writes `.last_index_update`.

Upstream `--since` uses `git log --since` on RST under `doc/` and **merges** into the existing FAISS index.

IBM has no git history. `--since` recrawls the IBM docs API, hash-compares against `--cache-dir`, and **skips** the FAISS rebuild when HTML is unchanged. Without `--cache-dir`, IBM always full-rebuilds.

## How the running MCP picks up the new index (no Cursor restart)

| Event | What the MCP does | Cursor |
|---|---|---|
| `./update_index.sh` finishes | Trigger watcher (~5s) calls `reload_from_disk()` — primary **and** IBM additional KBs | Stays open |
| `git pull` of `knowledge/` only | Same in-process reload | Stays open |
| `git pull` of any `*.py` | MCP `os._exit(0)`; Cursor respawns the subprocess | Stays open |
| No git remote | Pull skipped; trigger watcher still runs | Stays open |

Disable with `--no-auto-update`. Interval: `--update-interval HOURS` (default 1).

### Cursor MCP config

```json
{
  "command": "python",
  "args": ["-m", "ceph_doc_kb.server.mcp_server", "--auto-update", "--update-interval", "1"]
}
```

## Manual indexers

```bash
python3 index_docs.py --since 2026-08-01 --docs-path /tmp/ceph-docs/doc \
    --repo-path /tmp/ceph-docs --version 20.2.1 --verbose

python3 index_ibm_docs.py --version 9.1 --since 2026-08-01 \
    --cache-dir ./cache/ibm-9.1 --verbose

touch .reload_trigger
```

IBM versions: `8.0`, `8.1`, `9.0`, `9.1`.

## Files that must stay untracked

`.reload_trigger`, `.last_index_update`, and `cache/` are gitignored.

## Troubleshooting

| Symptom | Check |
|---|---|
| IBM pages still old after `--since` | Pass `--cache-dir`; otherwise IBM cannot hash-diff |
| Only upstream reloaded, IBM stale | Fixed by `reload_from_disk()` — confirm you are on a build that rediscovers `knowledge/doc-*/` |
| `CEPH_DOCS_REPO is not a git checkout` | Clone ceph, or `SKIP_UPSTREAM=1` for IBM-only |
