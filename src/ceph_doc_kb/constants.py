"""Shared constants for the ceph-doc-kb project."""

from __future__ import annotations

import re

CEPH_COMMAND_PREFIXES = (
    "ceph-bluestore-tool",
    "ceph-authtool",
    "ceph-volume",
    "ceph-fuse",
    "ceph-mds",
    "ceph-mgr",
    "ceph-mon",
    "ceph-osd",
    "ceph-rbdnamer",
    "cephadm",
    "ceph",
    "crushtool",
    "mount.ceph",
    "radosgw-admin",
    "rados",
    "rbd-mirror",
    "rbd-nbd",
    "rgw-orphan-list",
    "rbd",
)

# Ordered longest-first so regex matches the most specific prefix
_PREFIX_PATTERN = "|".join(re.escape(p) for p in sorted(CEPH_COMMAND_PREFIXES, key=len, reverse=True))

COMMAND_DETECTION_RE = re.compile(
    rf"(?:^|(?<=\s)|(?<=\$\s))({_PREFIX_PATTERN})(?=\s|$|[;|&)\"'])",
    re.MULTILINE,
)

COMMAND_WITH_SUBCOMMANDS_RE = re.compile(
    rf"(?:^|\s|\$\s+)({_PREFIX_PATTERN})"
    r"(\s+[\w\-]+(?:\s+[\w\-]+){0,3})",
    re.MULTILINE,
)

# Tokenizer shared between BM25 and code example search
STOPWORDS = frozenset({
    "a", "an", "the", "is", "it", "of", "in", "to", "and", "or", "for",
    "on", "with", "as", "at", "by", "from", "that", "this", "be", "are",
    "was", "were", "been", "being", "have", "has", "had", "do", "does",
    "did", "will", "would", "shall", "should", "may", "might", "can",
    "could", "not", "no", "but", "if", "so", "than", "too", "very",
    "just", "about", "above", "after", "below", "between", "into",
    "through", "during", "before", "each", "all", "any", "both",
    "other", "some", "such", "only", "own", "same", "also", "how",
    "what", "which", "who", "whom", "when", "where", "why",
})

TOKEN_RE = re.compile(r"[a-z0-9_\-/]+")


def tokenize(text: str) -> list[str]:
    """Tokenize text for keyword search — lowercase, stopword-filtered."""
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]
