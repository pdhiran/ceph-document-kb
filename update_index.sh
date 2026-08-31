#!/bin/bash
# Incremental doc-KB update. Same delta-date contract as ceph-issue-kb:
#   ./update_index.sh              # since last successful run (or last 1 day)
#   ./update_index.sh 7            # last 7 days
#   ./update_index.sh 2026-08-01   # since a specific ISO date
#   ./update_index.sh --reset      # clear the last-run tracker
#
# After a successful rebuild, touches .reload_trigger so a running MCP
# hot-reloads knowledge/ without restarting Cursor.
#
# Environment:
#   CEPH_DOCS_REPO   Path to a ceph git checkout with doc/ (default: /tmp/ceph-docs)
#   CEPH_VERSION     Upstream version label (default: 20.2.1)
#   IBM_VERSIONS     Space-separated IBM versions to recrawl (default: "9.1")
#   SKIP_IBM=1       Skip IBM recrawl
#   SKIP_UPSTREAM=1  Skip upstream RST incremental

set -euo pipefail
cd "$(dirname "$0")"

LAST_RUN_FILE=".last_index_update"
CEPH_DOCS_REPO="${CEPH_DOCS_REPO:-/tmp/ceph-docs}"
CEPH_VERSION="${CEPH_VERSION:-20.2.1}"
IBM_VERSIONS="${IBM_VERSIONS:-9.1}"

if [[ "${1:-}" == "--reset" ]]; then
    rm -f "$LAST_RUN_FILE"
    echo "Last-run tracker reset. Next run will fetch last 1 day."
    exit 0
fi

if [[ -n "${1:-}" ]]; then
    ARG="$1"
    if [[ "$ARG" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        SINCE="$ARG"
    else
        SINCE=$(date -v-"${ARG}"d +%Y-%m-%d 2>/dev/null || date -d "${ARG} days ago" +%Y-%m-%d)
    fi
elif [[ -f "$LAST_RUN_FILE" ]]; then
    SINCE=$(cat "$LAST_RUN_FILE")
    echo "(Last successful run: $SINCE)"
else
    SINCE=$(date -v-1d +%Y-%m-%d 2>/dev/null || date -d "1 day ago" +%Y-%m-%d)
    echo "(First run — fetching last 1 day)"
fi

echo "=== Ceph Doc KB Index Update ==="
echo "Delta since: $SINCE"
echo ""

if [[ "${SKIP_UPSTREAM:-0}" != "1" ]]; then
    if [[ ! -d "$CEPH_DOCS_REPO/.git" ]]; then
        echo "error: CEPH_DOCS_REPO=$CEPH_DOCS_REPO is not a git checkout" >&2
        echo "error: clone ceph first, or set SKIP_UPSTREAM=1 to only update IBM docs" >&2
        exit 1
    fi
    echo "--- Upstream RST ($CEPH_VERSION) ---"
    python3 index_docs.py \
        --since "$SINCE" \
        --docs-path "$CEPH_DOCS_REPO/doc" \
        --repo-path "$CEPH_DOCS_REPO" \
        --version "$CEPH_VERSION" \
        --verbose
fi

if [[ "${SKIP_IBM:-0}" != "1" ]]; then
    for ver in $IBM_VERSIONS; do
        echo "--- IBM Storage Ceph $ver ---"
        python3 index_ibm_docs.py \
            --version "$ver" \
            --since "$SINCE" \
            --cache-dir "./cache/ibm-$ver" \
            --verbose
    done
fi

touch .reload_trigger

date -v-1d +%Y-%m-%d > "$LAST_RUN_FILE" 2>/dev/null || date -d "1 day ago" +%Y-%m-%d > "$LAST_RUN_FILE"

echo ""
echo "=== Doc index updated since $SINCE ==="
echo "Touched .reload_trigger — running MCP hot-reloads within ~5s (no Cursor restart)."
