# Engineering Intelligence MCP Contract — ceph-doc-kb

This document describes how `ceph-doc-kb` implements the Engineering Intelligence MCP platform contract, enabling multi-KB orchestration with other Ceph knowledge bases (e.g., `ceph-cmd-kb`).

## Platform Vision

```
┌─────────────────────────────────────────────────────┐
│                   Agent / LLM                        │
│         (orchestrates multiple KBs)                  │
└──────┬──────────────┬──────────────┬────────────────┘
       │              │              │
       ▼              ▼              ▼
┌──────────┐   ┌──────────┐   ┌──────────┐
│ ceph-cmd │   │ ceph-doc │   │  future  │
│    KB    │   │    KB    │   │   KBs    │
│(commands)│   │  (docs)  │   │(err/rel) │
└──────────┘   └──────────┘   └──────────┘
```

Each KB exposes a consistent interface so agents can discover capabilities, check health, and query any KB without special-casing.

## Contract Implementation

### Mandatory Tools

| Tool | Description | Response |
|------|-------------|----------|
| `capabilities()` | Declare entity types, operations, version | `{entity_types, operations, version, ceph_version}` |
| `health()` | Report index status, coverage stats | `{status, version, ceph_version, total_chunks, components, ...}` |

### Entity Types

| Type | Description | ID Scheme |
|------|-------------|-----------|
| `doc_chunk` | A section of documentation (title + content) | `sha256(source_file::section_path)[:16]` |
| `code_example` | An extracted code block with context | `sha256(source_file::code[:100])[:16]` |
| `command_xref` | Cross-reference: command name → doc chunks | Keyed by normalized command string |

### Entity ID Generation

All entity IDs are 16-character hex strings derived from a SHA-256 hash of a stable key:

```python
entity_id = hashlib.sha256(f"{source_file}::{section_path}".encode()).hexdigest()[:16]
```

This ensures IDs are:
- **Stable** — same content always produces same ID
- **Unique** — collision probability negligible at this length
- **Reproducible** — can be regenerated from source metadata

### Version Awareness

Each Ceph release gets its own index directory:

```
knowledge/
  doc-20.2.1/     # Tentacle release
  doc-19.2.0/     # Squid release
```

The MCP server loads the latest available version by default, or a specific version via `--version` argument.

## Domain-Specific Tools

| Tool | Purpose | Complement to cmd-kb |
|------|---------|---------------------|
| `search_docs(query, component, limit)` | Semantic + keyword doc search | Provides context for commands |
| `search_examples(query, component, language, limit)` | Find code/config snippets | Provides usage examples |
| `get_doc_page(source_file)` | Full page content | Deep-dive after search |
| `find_docs_for_command(command)` | Instant command→doc lookup | Bridges cmd-kb → doc-kb |
| `list_components()` | Discover available doc sections | Scoping for targeted search |
| `list_topics(component)` | Topics within a component | Navigate doc hierarchy |

## Response Format

All tool responses are JSON. Search results follow a consistent schema:

```json
{
  "entity_id": "54bd25d35652c0f5",
  "title": "Section Title",
  "content": "Full section text...",
  "component": "rados",
  "topic": "operations",
  "source_file": "rados/operations/pools.rst",
  "section_path": "Pools > Creating a Pool",
  "doc_url": "https://docs.ceph.com/en/latest/rados/operations/pools/",
  "commands_referenced": ["ceph osd pool create"],
  "quality_score": 0.85,
  "score": 1.18,
  "search_source": "bm25",
  "deprecated": false
}
```

## Orchestration Pattern

An agent using both KBs follows this pattern:

```
1. User asks: "How do I set up erasure coding?"
2. Agent → ceph-doc-kb.list_components() → identifies "rados"
3. Agent → ceph-doc-kb.search_docs("erasure coding", component="rados")
4. Agent → ceph-cmd-kb.verify_command("ceph osd erasure-code-profile set")
5. Agent → ceph-cmd-kb.get_help("ceph osd pool create")
6. Agent synthesizes: verified commands + documentation context
```

The `find_docs_for_command` tool is the primary bridge — given any command from ceph-cmd-kb, it instantly finds the relevant documentation.

## Adding a New KB to the Platform

Any new KB (e.g., Error KB, Release KB) should:

1. Implement `capabilities()` and `health()` tools
2. Use 16-char hex entity IDs
3. Support version-scoped indices
4. Provide at least one search tool
5. Return results in the standard entity schema
6. Document entity types and their relationships to other KBs
