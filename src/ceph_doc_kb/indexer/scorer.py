"""Chunk quality scoring based on content characteristics."""

from __future__ import annotations

import re
from ceph_doc_kb.constants import COMMAND_DETECTION_RE
from ceph_doc_kb.models import DocChunk


# After rendering, code blocks are in markdown format (triple backticks)
CODE_BLOCK_PATTERN = re.compile(r'```', re.MULTILINE)
# ToC content is typically empty or has just references after rendering
TOC_INDICATORS = re.compile(r'toctree|contents::', re.IGNORECASE)


def score_chunk(chunk: DocChunk) -> float:
    """Compute quality score for a chunk. Higher = more useful."""
    score = 0.5
    content = chunk.content
    word_count = len(content.split())

    has_code = bool(CODE_BLOCK_PATTERN.search(content))
    has_commands = bool(COMMAND_DETECTION_RE.search(content))

    if has_code:
        score += 0.3

    if has_commands:
        score += 0.2

    has_prose = word_count > 30 and not content.strip().startswith('$')
    if has_code and has_prose:
        score += 0.2

    # Short titled chunks without code get a small bonus for being concise
    # reference entries, but very short chunks (< 20 words) still receive a
    # -0.2 penalty below — the net effect is intentional: titled but
    # extremely short chunks end up penalized overall.
    if word_count < 50 and chunk.title and not has_code:
        score += 0.1

    if TOC_INDICATORS.search(content):
        score -= 0.3

    if word_count >= 50:
        score += 0.1

    if word_count < 20:
        score -= 0.2

    if chunk.warnings:
        score += 0.1

    if chunk.deprecated:
        score -= 0.1

    return max(0.0, min(1.0, score))


def score_chunks(chunks: list[DocChunk]) -> list[DocChunk]:
    """Score all chunks in place and return the list."""
    for chunk in chunks:
        chunk.quality_score = score_chunk(chunk)
    return chunks
