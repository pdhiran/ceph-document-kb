"""Build command cross-reference index mapping commands to doc chunks."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from ceph_doc_kb.constants import COMMAND_WITH_SUBCOMMANDS_RE
from ceph_doc_kb.models import DocChunk


def _normalize_command(cmd: str) -> str:
    """Normalize a command string for consistent indexing."""
    return re.sub(r'\s+', ' ', cmd.strip()).lower()


def extract_commands_from_chunk(chunk: DocChunk) -> list[str]:
    """Extract all Ceph commands referenced in a chunk."""
    commands = set()
    text = f"{chunk.title}\n{chunk.content}"

    for match in COMMAND_WITH_SUBCOMMANDS_RE.finditer(text):
        prefix = match.group(1)
        rest = match.group(2).strip()
        subcommands = rest.split()
        for i in range(1, len(subcommands) + 1):
            cmd = f"{prefix} {' '.join(subcommands[:i])}"
            normalized = _normalize_command(cmd)
            if len(normalized.split()) >= 2:
                commands.add(normalized)

    return sorted(commands)


def build_xref(chunks: list[DocChunk]) -> dict[str, list[dict[str, str]]]:
    """Build command -> doc chunk cross-reference from all chunks."""
    xref: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen_per_cmd: dict[str, set[str]] = defaultdict(set)

    for chunk in chunks:
        commands = extract_commands_from_chunk(chunk)
        chunk.commands_referenced = commands

        for cmd in commands:
            if chunk.entity_id not in seen_per_cmd[cmd]:
                seen_per_cmd[cmd].add(chunk.entity_id)
                xref[cmd].append({
                    "chunk_id": chunk.entity_id,
                    "title": chunk.title,
                    "source": chunk.source_file,
                    "component": chunk.component,
                })

    return dict(xref)


def save_xref(xref: dict[str, list[dict[str, str]]], path: Path) -> None:
    """Save cross-reference index to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(xref, indent=2, sort_keys=True))


def load_xref(path: Path) -> dict[str, list[dict[str, str]]]:
    """Load cross-reference index from JSON file."""
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def lookup_command(xref: dict[str, list[dict[str, str]]], command: str) -> list[dict[str, str]]:
    """Look up documentation for a command. Tries exact match, then prefix match."""
    normalized = _normalize_command(command)

    if normalized in xref:
        return xref[normalized]

    # Prefix match: find all commands that start with the query
    results = []
    for cmd, entries in xref.items():
        if cmd.startswith(normalized):
            results.extend(entries)

    # Deduplicate by chunk_id
    seen = set()
    unique = []
    for entry in results:
        if entry["chunk_id"] not in seen:
            seen.add(entry["chunk_id"])
            unique.append(entry)

    return unique
