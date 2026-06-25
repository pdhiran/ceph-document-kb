# Agent Integration Guide — ceph-doc-kb

This guide covers integrating the Ceph documentation knowledge base with LLM agents, including IBM watsonx (Bob), LangChain, CrewAI, and custom agent frameworks.

## Architecture

```
┌─────────────────────┐       ┌──────────────────────┐
│    Agent / LLM      │       │   ceph-doc-kb        │
│  (Bob, LangChain,   │──────▶│   REST API           │
│   CrewAI, custom)   │ HTTP  │   :8100              │
└─────────────────────┘       └──────────────────────┘
         │                              │
         │ MCP (stdio)                  │ reads
         ▼                              ▼
┌─────────────────────┐       ┌──────────────────────┐
│   ceph-doc-kb       │       │   knowledge/         │
│   MCP Server        │       │   doc-20.2.1/        │
└─────────────────────┘       └──────────────────────┘
```

Two integration paths:
- **REST API** — for any HTTP client (agents, web apps, scripts)
- **MCP** — for Cursor, Claude Desktop, and MCP-compatible tools

## REST API Reference

Base URL: `http://localhost:8100`

### Search Documentation

```bash
curl "http://localhost:8100/api/search?query=erasure+coding+pool&component=rados&limit=5"
```

Response:
```json
{
  "query": "erasure coding pool",
  "component": "rados",
  "results": [
    {
      "entity_id": "54bd25d35652c0f5",
      "title": "Not enough OSDs",
      "content": "If the Ceph cluster has only eight OSDs...",
      "component": "rados",
      "topic": "troubleshooting",
      "source_file": "rados/troubleshooting/troubleshooting-pg.rst",
      "doc_url": "https://docs.ceph.com/en/latest/rados/troubleshooting/troubleshooting-pg/",
      "score": 1.18
    }
  ]
}
```

### Search Code Examples

```bash
curl "http://localhost:8100/api/examples?query=ceph+osd+pool+create&language=bash&limit=3"
```

### Find Docs for Command

```bash
curl "http://localhost:8100/api/command/ceph%20osd%20pool%20create"
```

### Get Full Doc Page

```bash
curl "http://localhost:8100/api/doc/rados/operations/pools.rst"
```

### List Components

```bash
curl "http://localhost:8100/api/components"
```

### List Topics

```bash
curl "http://localhost:8100/api/components/rados/topics"
```

### Health Check

```bash
curl "http://localhost:8100/api/health"
```

## Python Client

See [`examples/agent_integration.py`](examples/agent_integration.py) for a ready-made client class.

```python
from examples.agent_integration import CephDocKBClient

client = CephDocKBClient("http://localhost:8100")

# Search docs
results = client.search_docs("erasure coding", component="rados", limit=5)
for r in results:
    print(f"{r['title']} ({r['source_file']})")

# Find docs for a command
refs = client.find_docs_for_command("ceph osd pool create")

# Get code examples
examples = client.search_examples("bootstrap cluster", component="cephadm", language="bash")
```

## LangChain Integration

```python
from langchain.tools import Tool
from examples.agent_integration import CephDocKBClient

client = CephDocKBClient()

search_docs_tool = Tool(
    name="search_ceph_docs",
    description="Search Ceph documentation. Use 'component' param to scope (rados, cephfs, rbd, radosgw, cephadm).",
    func=lambda query: client.search_docs(query, limit=5),
)

find_command_docs_tool = Tool(
    name="find_docs_for_command",
    description="Find documentation pages for a specific Ceph CLI command.",
    func=lambda cmd: client.find_docs_for_command(cmd),
)

search_examples_tool = Tool(
    name="search_ceph_examples",
    description="Search for code examples in Ceph documentation.",
    func=lambda query: client.search_examples(query, language="bash", limit=5),
)
```

## CrewAI Integration

```python
from crewai import Agent, Task
from crewai_tools import tool
from examples.agent_integration import CephDocKBClient

client = CephDocKBClient()

@tool("Search Ceph Documentation")
def search_ceph_docs(query: str, component: str = "") -> str:
    """Search Ceph documentation by keyword or concept. Component can be: rados, cephfs, rbd, radosgw, cephadm."""
    results = client.search_docs(query, component=component or None, limit=5)
    return "\n\n".join(f"## {r['title']}\n{r['content'][:200]}..." for r in results)

@tool("Find Docs for Ceph Command")
def find_docs_for_command(command: str) -> str:
    """Find documentation for a specific Ceph command like 'ceph osd pool create'."""
    refs = client.find_docs_for_command(command)
    return "\n".join(f"- {r['title']} ({r['source']})" for r in refs)

ceph_agent = Agent(
    role="Ceph Storage Expert",
    goal="Help with Ceph cluster operations using official documentation",
    tools=[search_ceph_docs, find_docs_for_command],
)
```

## Combined Workflow (ceph-doc-kb + ceph-cmd-kb)

For maximum accuracy, use both KBs together:

```python
from examples.agent_integration import CephDocKBClient
import requests

doc_client = CephDocKBClient("http://localhost:8100")
cmd_api = "http://localhost:9090"

def answer_ceph_question(question: str) -> dict:
    """Full workflow: search docs → verify commands → return answer."""
    
    # Step 1: Search docs for context
    docs = doc_client.search_docs(question, limit=5)
    
    # Step 2: Extract commands from results
    commands = set()
    for d in docs:
        commands.update(d.get("commands_referenced", []))
    
    # Step 3: Verify each command with cmd-kb
    verified = {}
    for cmd in commands:
        resp = requests.post(f"{cmd_api}/api/verify_command", json={"command": cmd})
        verified[cmd] = resp.json()
    
    # Step 4: Get code examples
    examples = doc_client.search_examples(question, language="bash", limit=3)
    
    return {
        "documentation": docs,
        "verified_commands": verified,
        "code_examples": examples,
    }
```

## Deployment

### systemd Service

```ini
[Unit]
Description=Ceph Documentation KB REST API
After=network.target

[Service]
Type=simple
User=ceph-kb
WorkingDirectory=/opt/ceph-doc-kb
ExecStart=/opt/ceph-doc-kb/.venv/bin/python3 -m ceph_doc_kb.server.rest_api
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -e .
EXPOSE 8100
CMD ["python3", "-m", "ceph_doc_kb.server.rest_api", "--host", "0.0.0.0"]
```

```bash
docker build -t ceph-doc-kb .
docker run -p 8100:8100 ceph-doc-kb
```

## Agent Prompt Best Practices

When integrating with an LLM agent, include these instructions in the system prompt:

```
You have access to the Ceph Documentation KB. Use it as follows:

1. For "how do I..." questions → search_docs with the relevant component
2. For command syntax questions → find_docs_for_command first (instant), 
   then search_docs for context if needed
3. For config/deployment examples → search_examples with language="bash" or "yaml"
4. Always scope to a component when possible (rados, cephfs, rbd, radosgw, cephadm)
5. Cross-reference with ceph-cmd-kb to verify command syntax before recommending
```
