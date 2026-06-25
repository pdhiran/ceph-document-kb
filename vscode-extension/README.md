# Ceph Documentation KB — VS Code Extension

Search and browse Ceph documentation directly from VS Code, powered by the ceph-doc-kb REST API.

## Prerequisites

The ceph-doc-kb REST API server must be running:

```bash
cd /path/to/ceph-doc-kb
python3 -m ceph_doc_kb.server.rest_api
# Server starts on http://localhost:8100
```

## Installation

### From Source

```bash
cd vscode-extension
npm install
# Then in VS Code: "Developer: Install Extension from Location..."
```

### As VSIX

```bash
cd vscode-extension
npm install
npx vsce package
code --install-extension ceph-doc-kb-vscode-0.1.0.vsix
```

## Features

| Command | Keybinding | Description |
|---------|-----------|-------------|
| Search Documentation | `Cmd+Alt+D` | Search docs by keyword or concept, with optional component scoping |
| Search Code Examples | `Cmd+Alt+E` | Find code snippets (bash, yaml, json) and insert at cursor |
| Find Docs for Command | `Cmd+Alt+F` | Look up docs for a Ceph command (uses selection or input) |
| Get Doc Page | — | View a full documentation page by RST source path |
| List Components | — | Browse indexed components and their coverage |

## Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `ceph-doc-kb.apiUrl` | `http://localhost:8100` | REST API server URL |
| `ceph-doc-kb.defaultComponent` | `""` | Default component scope (empty = prompt each time) |

## Workflow

1. **Search docs** — Hit `Cmd+Alt+D`, type your question, pick a component, browse results
2. **Insert examples** — Hit `Cmd+Alt+E`, search for command examples, insert directly into your editor
3. **Command lookup** — Select a Ceph command in your code, hit `Cmd+Alt+F` to find its documentation
4. **Combined with ceph-cmd-kb** — Use ceph-cmd-kb to verify command syntax, ceph-doc-kb to get context and examples

## Status Bar

The status bar shows connection state:
- `$(book) Ceph Docs: 5927 chunks` — connected, showing indexed chunk count
- `$(warning) Ceph Docs: No index` — connected but no index loaded
- `$(error) Ceph Docs: Offline` — cannot reach the REST API
