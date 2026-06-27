"""Orchestrator: parse → score → embed → store."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ceph_doc_kb.models import DocChunk, IndexMetadata, ComponentIndex
from ceph_doc_kb.indexer.parser import _detect_component_and_topic
from ceph_doc_kb.indexer.scorer import score_chunks
from ceph_doc_kb.indexer.code_extractor import extract_code_blocks
from ceph_doc_kb.indexer.xref import build_xref, save_xref
from ceph_doc_kb.indexer.embedder import Embedder, IndexBuilder

logger = logging.getLogger(__name__)


def build_index(
    docs_path: Path,
    output_path: Path,
    version: str,
    model_name: str = "BAAI/bge-small-en-v1.5",
    verbose: bool = False,
) -> IndexMetadata:
    """Full index build pipeline.

    1. Parse RST files into DocChunks
    2. Score chunks for quality
    3. Extract code examples
    4. Build command cross-reference
    5. Embed and build FAISS indices
    6. Write metadata
    """
    from ceph_doc_kb.indexer.parser import parse_docs_directory

    if verbose:
        logging.basicConfig(level=logging.INFO)

    logger.info(f"Parsing RST files from {docs_path}...")
    chunks = parse_docs_directory(docs_path, version=version)
    logger.info(f"Parsed {len(chunks)} chunks")

    if not chunks:
        raise ValueError(f"No chunks parsed from {docs_path}. Check the docs path.")

    logger.info("Scoring chunks...")
    score_chunks(chunks)

    # TODO: Each RST file is read twice (once by parser, once here for code
    # extraction). Consolidating requires changing the parser API to return
    # raw content alongside chunks — non-trivial refactor deferred.
    logger.info("Extracting code examples...")
    all_code_examples = []
    code_by_component: dict[str, list] = defaultdict(list)
    for rst_file in docs_path.rglob("*.rst"):
        try:
            content = rst_file.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        rel_path = str(rst_file.relative_to(docs_path))
        component, _ = _detect_component_and_topic(rel_path)
        examples = extract_code_blocks(content, rel_path, component)
        all_code_examples.extend(examples)
        code_by_component[component].extend(examples)

    logger.info(f"Extracted {len(all_code_examples)} code examples")

    logger.info("Building command cross-reference...")
    xref = build_xref(chunks)
    logger.info(f"Cross-referenced {len(xref)} commands")

    logger.info("Grouping chunks by component...")
    chunks_by_component: dict[str, list[DocChunk]] = defaultdict(list)
    for chunk in chunks:
        chunks_by_component[chunk.component].append(chunk)

    logger.info("Building embeddings and FAISS indices...")
    embedder = Embedder(model_name)
    builder = IndexBuilder(embedder, model_name)

    output_path.mkdir(parents=True, exist_ok=True)
    component_counts = builder.build_all_components(chunks_by_component, output_path)

    # Save code examples per component
    for component, examples in code_by_component.items():
        comp_dir = output_path / component
        comp_dir.mkdir(parents=True, exist_ok=True)
        code_path = comp_dir / "code_examples.json"
        code_path.write_text(json.dumps([e.to_dict() for e in examples], indent=2))

    save_xref(xref, output_path / "command_xref.json")

    # Build metadata
    components = {}
    for comp_name, count in component_counts.items():
        topics = sorted(set(c.topic for c in chunks_by_component[comp_name] if c.topic))
        code_count = len(code_by_component.get(comp_name, []))
        components[comp_name] = ComponentIndex(
            name=comp_name,
            chunk_count=count,
            code_example_count=code_count,
            topics=topics,
            faiss_index_path=f"{comp_name}/faiss.index",
            chunks_path=f"{comp_name}/chunks.json",
            code_examples_path=f"{comp_name}/code_examples.json",
        )

    metadata = IndexMetadata(
        version="1.0",
        ceph_version=version,
        embedding_model=model_name,
        embedding_dimensions=builder.dimensions,
        total_chunks=len(chunks),
        total_code_examples=len(all_code_examples),
        components=components,
        build_timestamp=datetime.now(timezone.utc).isoformat(),
    )
    metadata.save(output_path / "metadata.json")

    logger.info(f"Index built: {len(chunks)} chunks, {len(all_code_examples)} code examples, "
                f"{len(component_counts)} components")

    return metadata
