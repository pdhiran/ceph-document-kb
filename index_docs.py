#!/usr/bin/env python3
"""CLI: Build or update the Ceph documentation knowledge base index."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build or update Ceph documentation index",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full build
  python index_docs.py --docs-path /tmp/ceph-docs/doc --version 20.2.1

  # Incremental update
  python index_docs.py --update --docs-path /tmp/ceph-docs/doc \\
      --repo-path /tmp/ceph-docs --from-version v20.2.1 --to-version v20.2.2

  # Custom output directory
  python index_docs.py --docs-path ./doc --version 20.2.1 --output ./my-index
        """,
    )

    parser.add_argument(
        "--docs-path",
        type=Path,
        required=True,
        help="Path to the Ceph doc/ directory",
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Ceph version string (e.g. '20.2.1')",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: knowledge/doc-{version})",
    )
    parser.add_argument(
        "--model",
        default="BAAI/bge-small-en-v1.5",
        help="Embedding model name (default: BAAI/bge-small-en-v1.5)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    # Incremental update options
    parser.add_argument(
        "--update",
        action="store_true",
        help="Perform incremental update instead of full build",
    )
    parser.add_argument(
        "--repo-path",
        type=Path,
        default=None,
        help="Path to the ceph git repo (for incremental updates)",
    )
    parser.add_argument(
        "--from-version",
        default=None,
        help="Previous version tag (for incremental updates)",
    )
    parser.add_argument(
        "--to-version",
        default=None,
        help="New version tag (for incremental updates)",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    if not args.docs_path.exists():
        logger.error(f"Docs path does not exist: {args.docs_path}")
        return 1

    output = args.output or Path(f"knowledge/doc-{args.version}")

    if args.update:
        if not args.repo_path or not args.from_version or not args.to_version:
            logger.error("--update requires --repo-path, --from-version, and --to-version")
            return 1

        from ceph_doc_kb.indexer.incremental import incremental_update

        metadata = incremental_update(
            docs_path=args.docs_path,
            repo_path=args.repo_path,
            index_path=output,
            from_version=args.from_version,
            to_version=args.to_version,
            model_name=args.model,
        )
    else:
        from ceph_doc_kb.indexer.builder import build_index

        metadata = build_index(
            docs_path=args.docs_path,
            output_path=output,
            version=args.version,
            model_name=args.model,
            verbose=args.verbose,
        )

    print(f"\nIndex built successfully!")
    print(f"  Output: {output}")
    print(f"  Ceph version: {metadata.ceph_version}")
    print(f"  Total chunks: {metadata.total_chunks}")
    print(f"  Total code examples: {metadata.total_code_examples}")
    print(f"  Components: {len(metadata.components)}")
    for comp_name, comp in sorted(metadata.components.items()):
        print(f"    {comp_name}: {comp.chunk_count} chunks, {comp.code_example_count} examples")

    return 0


if __name__ == "__main__":
    sys.exit(main())
