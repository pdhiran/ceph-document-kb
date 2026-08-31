#!/usr/bin/env python3
"""CLI: Build IBM Storage Ceph documentation index from ibm.com/docs.

Crawls the IBM documentation portal, parses HTML pages, and builds
a FAISS-indexed knowledge base compatible with the upstream doc KB.

Usage:
    # Index IBM Storage Ceph 8.1 docs
    python index_ibm_docs.py --version 8.1

    # Index with custom output directory
    python index_ibm_docs.py --version 8.1 --output ./knowledge/ibm-8.1

    # Index from previously saved HTML (offline mode)
    python index_ibm_docs.py --version 8.1 --cache-dir ./ibm-docs-cache

    # Limit pages for testing
    python index_ibm_docs.py --version 8.1 --max-pages 5 --verbose
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build IBM Storage Ceph documentation index from ibm.com/docs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full index build for IBM Storage Ceph 8.1
  python index_ibm_docs.py --version 8.1 --verbose

  # Quick test with limited pages
  python index_ibm_docs.py --version 8.1 --max-pages 5 --verbose

  # Use cached HTML (skip crawling)
  python index_ibm_docs.py --version 8.1 --cache-dir ./cache/ibm-8.1

  # Index both 8.0 and 8.1
  python index_ibm_docs.py --version 8.0 --verbose
  python index_ibm_docs.py --version 8.1 --verbose

  # Incremental: recrawl, skip rebuild if HTML hashes match the cache
  python index_ibm_docs.py --version 9.1 --since 2026-08-01 \\
      --cache-dir ./cache/ibm-9.1 --verbose
        """,
    )

    parser.add_argument(
        "--version",
        required=True,
        help="IBM Storage Ceph version (e.g. '8.0', '8.1')",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: knowledge/doc-ibm-{version})",
    )
    parser.add_argument(
        "--model",
        default="BAAI/bge-small-en-v1.5",
        help="Embedding model name (default: BAAI/bge-small-en-v1.5)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Directory to cache/load raw HTML pages (enables offline re-indexing)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Maximum pages to crawl (for testing)",
    )
    parser.add_argument(
        "--throttle",
        type=float,
        default=1.0,
        help="Seconds between requests (default: 1.0)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--since",
        metavar="YYYY-MM-DD",
        default=None,
        help=(
            "Delta update: recrawl IBM docs and rebuild only if page HTML "
            "changed since the last cached crawl. Records this date in "
            "ibm_crawl_metadata.json. Same CLI contract as "
            "python index_issues.py --since DATE"
        ),
    )

    args = parser.parse_args()

    log_level = logging.INFO if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from ceph_doc_kb.constants import IBM_VERSIONS
    from ceph_doc_kb.indexer.incremental import parse_since_date

    if args.since:
        try:
            parse_since_date(args.since)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    if args.version not in IBM_VERSIONS:
        print(f"Error: Unknown IBM version '{args.version}'. "
              f"Available: {list(IBM_VERSIONS.keys())}", file=sys.stderr)
        return 1

    output = args.output or Path(f"knowledge/doc-ibm-{args.version}")

    # Phase 1: Crawl or load from cache
    if args.since:
        pages = _crawl_live(args)
        if not pages:
            print("Error: No pages to index.", file=sys.stderr)
            return 1
        if args.cache_dir:
            changed = _changed_pages_vs_cache(pages, args.cache_dir)
            _save_to_cache(pages, args.cache_dir)
            if (
                not changed
                and (output / "metadata.json").exists()
            ):
                print(
                    f"No IBM pages changed since last crawl "
                    f"({len(pages)} pages identical) — skipping rebuild"
                )
                _stamp_ibm_since(output, args)
                return 0
            if changed:
                print(f"  {len(changed)} of {len(pages)} pages changed since last crawl")
    else:
        pages = _get_pages(args)
        if not pages:
            print("Error: No pages to index.", file=sys.stderr)
            return 1

    print(f"\nPhase 1 complete: {len(pages)} pages available")

    # Phase 2: Parse HTML into DocChunks
    from ceph_doc_kb.indexer.ibm_parser import (
        extract_code_examples_from_page,
        parse_ibm_page,
    )

    all_chunks = []
    all_code_examples = []
    chunks_by_component: dict[str, list] = defaultdict(list)
    code_by_component: dict[str, list] = defaultdict(list)

    for page in pages:
        chunks = parse_ibm_page(
            html=page["html"],
            url=page["url"],
            topic_slug=page["topic_slug"],
            version=args.version,
        )
        all_chunks.extend(chunks)
        for chunk in chunks:
            chunks_by_component[chunk.component].append(chunk)

        examples = extract_code_examples_from_page(
            html=page["html"],
            topic_slug=page["topic_slug"],
            version=args.version,
        )
        all_code_examples.extend(examples)
        for ex in examples:
            code_by_component[ex.component].append(ex)

    print(f"Phase 2 complete: {len(all_chunks)} chunks, "
          f"{len(all_code_examples)} code examples from "
          f"{len(chunks_by_component)} components")

    if not all_chunks:
        print("Error: No content extracted from pages.", file=sys.stderr)
        return 1

    # Phase 3: Score, embed, and build FAISS indices
    from ceph_doc_kb.indexer.scorer import score_chunks
    from ceph_doc_kb.indexer.xref import build_xref, save_xref
    from ceph_doc_kb.indexer.embedder import Embedder, IndexBuilder
    from ceph_doc_kb.models import IndexMetadata, ComponentIndex

    print("Phase 3: Scoring chunks...")
    score_chunks(all_chunks)

    print("Phase 3: Building command cross-reference...")
    xref = build_xref(all_chunks)
    print(f"  Cross-referenced {len(xref)} commands")

    print("Phase 3: Building embeddings and FAISS indices...")
    embedder = Embedder(args.model)
    builder = IndexBuilder(embedder, args.model)

    output.mkdir(parents=True, exist_ok=True)
    component_counts = builder.build_all_components(chunks_by_component, output)

    # Save code examples per component
    for component, examples in code_by_component.items():
        comp_dir = output / component
        comp_dir.mkdir(parents=True, exist_ok=True)
        code_path = comp_dir / "code_examples.json"
        code_path.write_text(json.dumps([e.to_dict() for e in examples], indent=2))

    save_xref(xref, output / "command_xref.json")

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
        ceph_version=f"ibm-{args.version}",
        embedding_model=args.model,
        embedding_dimensions=builder.dimensions,
        total_chunks=len(all_chunks),
        total_code_examples=len(all_code_examples),
        components=components,
        build_timestamp=datetime.now(timezone.utc).isoformat(),
        last_incremental_since=args.since or "",
    )
    metadata.save(output / "metadata.json")

    # Save crawl metadata for provenance
    crawl_meta = {
        "ibm_version": args.version,
        "url_version": IBM_VERSIONS[args.version]["url_version"],
        "upstream_equivalent": IBM_VERSIONS[args.version]["ceph_upstream"],
        "pages_indexed": len(pages),
        "build_timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "https://www.ibm.com/docs/en/storage-ceph",
        "updated_since": args.since or "",
    }
    (output / "ibm_crawl_metadata.json").write_text(json.dumps(crawl_meta, indent=2))

    print(f"\nIndex built successfully!")
    print(f"  Output: {output}")
    print(f"  IBM version: {args.version}")
    print(f"  Pages indexed: {len(pages)}")
    print(f"  Total chunks: {metadata.total_chunks}")
    print(f"  Total code examples: {metadata.total_code_examples}")
    print(f"  Components: {len(metadata.components)}")
    for comp_name, comp in sorted(metadata.components.items()):
        print(f"    {comp_name}: {comp.chunk_count} chunks, "
              f"{comp.code_example_count} examples")

    return 0


def _get_pages(args) -> list[dict]:
    """Get pages from cache or by crawling."""
    cache_dir = args.cache_dir

    if cache_dir and cache_dir.exists() and (cache_dir / "manifest.json").exists():
        return _load_from_cache(cache_dir)

    pages = _crawl_live(args)
    if cache_dir and pages:
        _save_to_cache(pages, cache_dir)
    return pages


def _crawl_live(args) -> list[dict]:
    """Crawl IBM docs API (always hits the network)."""
    from ceph_doc_kb.indexer.ibm_crawler import crawl_version

    print(f"Crawling IBM Storage Ceph {args.version} documentation...")
    print(f"  Using IBM docs API (no scraping)")
    print(f"  Throttle: {args.throttle}s between requests")
    if args.max_pages:
        print(f"  Max pages: {args.max_pages}")

    result = crawl_version(
        version=args.version,
        throttle=args.throttle,
        max_pages=args.max_pages,
    )

    pages = [
        {
            "url": p.url,
            "topic_slug": p.topic_id,
            "html": p.html,
            "label": p.label,
            "parent_section": p.parent_section,
        }
        for p in result.pages
    ]

    print(f"  Total topics in TOC: {result.total_topics}")
    print(f"  Skipped (release notes details, etc.): {result.skipped_topics}")
    if result.failed_hrefs:
        print(f"  Failed to fetch: {len(result.failed_hrefs)}")

    return pages


def _page_hash(html: str) -> str:
    return hashlib.sha256(html.encode("utf-8", errors="replace")).hexdigest()


def _changed_pages_vs_cache(pages: list[dict], cache_dir: Path) -> list[dict]:
    """Return pages whose HTML hash differs from the existing cache."""
    if not cache_dir.exists() or not (cache_dir / "manifest.json").exists():
        return pages

    old_hashes: dict[str, str] = {}
    try:
        manifest = json.loads((cache_dir / "manifest.json").read_text())
    except (json.JSONDecodeError, OSError):
        return pages

    for entry in manifest:
        html_path = cache_dir / entry.get("filename", "")
        if not html_path.exists():
            continue
        try:
            old_hashes[entry["topic_slug"]] = _page_hash(
                html_path.read_text(encoding="utf-8")
            )
        except OSError:
            continue

    changed = []
    for page in pages:
        slug = page["topic_slug"]
        if old_hashes.get(slug) != _page_hash(page["html"]):
            changed.append(page)
    return changed


def _stamp_ibm_since(output: Path, args) -> None:
    """Record a no-op delta run on existing crawl metadata."""
    meta_path = output / "ibm_crawl_metadata.json"
    data = {}
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
    data["updated_since"] = args.since or ""
    data["last_delta_check"] = datetime.now(timezone.utc).isoformat()
    meta_path.write_text(json.dumps(data, indent=2))

    idx_meta = output / "metadata.json"
    if idx_meta.exists():
        try:
            from ceph_doc_kb.models import IndexMetadata
            metadata = IndexMetadata.load(idx_meta)
            metadata.last_incremental_since = args.since or ""
            metadata.save(idx_meta)
        except Exception:
            logger.warning("Could not stamp last_incremental_since on %s", idx_meta)


def _load_from_cache(cache_dir: Path) -> list[dict]:
    """Load previously cached HTML pages."""
    manifest_path = cache_dir / "manifest.json"
    if not manifest_path.exists():
        logger.error("No manifest.json found in cache dir: %s", cache_dir)
        return []

    manifest = json.loads(manifest_path.read_text())
    pages = []
    for entry in manifest:
        html_path = cache_dir / entry["filename"]
        if html_path.exists():
            pages.append({
                "url": entry["url"],
                "topic_slug": entry["topic_slug"],
                "html": html_path.read_text(encoding="utf-8"),
                "label": entry.get("label", ""),
                "parent_section": entry.get("parent_section", ""),
            })
    print(f"Loaded {len(pages)} pages from cache: {cache_dir}")
    return pages


def _save_to_cache(pages: list[dict], cache_dir: Path) -> None:
    """Save crawled pages to disk for offline re-indexing."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, page in enumerate(pages):
        filename = f"{page['topic_slug']}.html"
        (cache_dir / filename).write_text(page["html"], encoding="utf-8")
        manifest.append({
            "url": page["url"],
            "topic_slug": page["topic_slug"],
            "label": page.get("label", ""),
            "parent_section": page.get("parent_section", ""),
            "filename": filename,
        })
    (cache_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Cached {len(pages)} pages to: {cache_dir}")


if __name__ == "__main__":
    sys.exit(main())
