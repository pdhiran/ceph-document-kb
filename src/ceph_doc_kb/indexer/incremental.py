"""Incremental re-indexing via git diff between version tags."""

from __future__ import annotations

import json
import logging
import subprocess
from collections import defaultdict
from pathlib import Path

from ceph_doc_kb.models import DocChunk, IndexMetadata, ComponentIndex
from ceph_doc_kb.indexer.parser import parse_rst_file
from ceph_doc_kb.indexer.scorer import score_chunks
from ceph_doc_kb.indexer.code_extractor import extract_code_blocks
from ceph_doc_kb.indexer.xref import build_xref, save_xref
from ceph_doc_kb.indexer.embedder import Embedder, IndexBuilder

logger = logging.getLogger(__name__)


def get_changed_files(
    repo_path: Path,
    from_version: str,
    to_version: str,
) -> list[str]:
    """Get list of changed RST files between two git tags."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{from_version}..{to_version}", "--", "doc/"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"git diff timed out after 60s for {from_version}..{to_version}")
    if result.returncode != 0:
        raise RuntimeError(f"git diff failed: {result.stderr}")

    files = [f for f in result.stdout.strip().split('\n') if f.endswith('.rst')]
    return files


def incremental_update(
    docs_path: Path,
    repo_path: Path,
    index_path: Path,
    from_version: str,
    to_version: str,
    model_name: str = "BAAI/bge-small-en-v1.5",
) -> IndexMetadata:
    """Update index incrementally based on changed files between versions.

    Only re-parses and re-embeds chunks from files that changed.
    Preserves unchanged component indices.
    """
    changed_files = get_changed_files(repo_path, from_version, to_version)
    if not changed_files:
        logger.info("No RST files changed between versions.")
        existing = IndexMetadata.load(index_path / "metadata.json")
        return existing

    logger.info(f"Found {len(changed_files)} changed RST files")

    # Determine which components are affected
    affected_components: dict[str, list[str]] = defaultdict(list)
    for f in changed_files:
        # Strip leading "doc/" prefix if present
        rel = f.removeprefix("doc/")
        parts = rel.split('/')
        component = parts[0] if parts else "other"
        affected_components[component].append(rel)

    logger.info(f"Affected components: {list(affected_components.keys())}")

    # Load existing metadata and chunks for affected components
    existing_metadata = IndexMetadata.load(index_path / "metadata.json")

    # Re-parse changed files
    new_chunks_by_component: dict[str, list[DocChunk]] = defaultdict(list)
    new_code_by_component: dict[str, list] = defaultdict(list)

    for component, files in affected_components.items():
        # Load existing chunks for this component (excluding changed files)
        comp_chunks_path = index_path / component / "chunks.json"
        existing_chunks = []
        if comp_chunks_path.exists():
            data = json.loads(comp_chunks_path.read_text())
            existing_chunks = [
                DocChunk.from_dict(d) for d in data
                if d["source_file"] not in files
            ]

        # Parse changed files
        for rel_file in files:
            file_path = docs_path / rel_file
            if not file_path.exists():
                continue
            parsed = parse_rst_file(file_path, docs_path, version=to_version)
            new_chunks_by_component[component].extend(parsed)

            try:
                content = file_path.read_text(encoding='utf-8', errors='replace')
            except OSError:
                logger.warning("File disappeared before read: %s", file_path)
                continue
            examples = extract_code_blocks(content, rel_file, component)
            new_code_by_component[component].extend(examples)

        # Combine existing + new chunks
        all_component_chunks = existing_chunks + new_chunks_by_component[component]
        score_chunks(all_component_chunks)
        new_chunks_by_component[component] = all_component_chunks

    # Rebuild indices only for affected components
    embedder = Embedder(model_name)
    builder = IndexBuilder(embedder, model_name)

    for component, chunks in new_chunks_by_component.items():
        comp_dir = index_path / component
        builder.build_component_index(chunks, comp_dir)

        # Merge code examples: keep existing examples from unchanged files
        code_path = comp_dir / "code_examples.json"
        existing_examples = []
        if code_path.exists():
            try:
                existing_data = json.loads(code_path.read_text())
                changed_set = set(affected_components.get(component, []))
                existing_examples = [
                    e for e in existing_data
                    if e.get("source_file") not in changed_set
                ]
            except (json.JSONDecodeError, OSError):
                logger.warning("Failed to load existing code examples for %s", component)

        merged_examples = existing_examples + [
            e.to_dict() for e in new_code_by_component[component]
        ]
        if merged_examples:
            code_path.write_text(json.dumps(merged_examples, indent=2))

    # Rebuild xref from all chunks (including newly added components)
    all_component_names = set(existing_metadata.components) | set(affected_components)
    all_chunks = []
    for comp_name in all_component_names:
        chunks_path = index_path / comp_name / "chunks.json"
        if chunks_path.exists():
            data = json.loads(chunks_path.read_text())
            all_chunks.extend(DocChunk.from_dict(d) for d in data)

    xref = build_xref(all_chunks)
    save_xref(xref, index_path / "command_xref.json")

    # Update metadata
    for component in affected_components:
        chunks_path = index_path / component / "chunks.json"
        if chunks_path.exists():
            data = json.loads(chunks_path.read_text())
            chunk_count = len(data)
        else:
            chunk_count = 0

        code_path = index_path / component / "code_examples.json"
        code_count = 0
        if code_path.exists():
            code_count = len(json.loads(code_path.read_text()))

        topics = sorted(set(
            c.topic for c in new_chunks_by_component.get(component, []) if c.topic
        ))

        existing_metadata.components[component] = ComponentIndex(
            name=component,
            chunk_count=chunk_count,
            code_example_count=code_count,
            topics=topics,
            faiss_index_path=f"{component}/faiss.index",
            chunks_path=f"{component}/chunks.json",
            code_examples_path=f"{component}/code_examples.json",
        )

    existing_metadata.ceph_version = to_version
    existing_metadata.total_chunks = sum(
        c.chunk_count for c in existing_metadata.components.values()
    )
    existing_metadata.total_code_examples = sum(
        c.code_example_count for c in existing_metadata.components.values()
    )
    existing_metadata.save(index_path / "metadata.json")

    logger.info(f"Incremental update complete: {len(changed_files)} files, "
                f"{len(affected_components)} components updated")

    return existing_metadata
