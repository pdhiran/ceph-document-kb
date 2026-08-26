"""Crawler for IBM Storage Ceph documentation at ibm.com/docs.

Uses the IBM Documentation REST API to:
1. Fetch the full table of contents (TOC) tree
2. Fetch individual topic HTML content

This avoids fragile HTML scraping and works reliably with proper throttling.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

from ceph_doc_kb.constants import IBM_DOCS_BASE_URL, IBM_VERSIONS

logger = logging.getLogger(__name__)

IBM_DOCS_API_BASE = "https://www.ibm.com/docs/api/v1"
REQUEST_TIMEOUT = 30.0
THROTTLE_SECONDS = 0.5
MAX_RETRIES = 3

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "en-US,en;q=0.5",
}

# Topic categories to skip (not useful for technical KB)
_SKIP_TOPIC_IDS = frozenset({
    "dummy-landing-page-id",
    "notices",
    "acknowledgments",
    "glossary",
    "related-information",
})


@dataclass
class TocEntry:
    """A single entry from the IBM docs table of contents."""

    topic_id: str
    label: str
    href: str
    depth: int = 0
    parent_label: str = ""


@dataclass
class CrawledPage:
    """A single fetched IBM documentation page."""

    url: str
    topic_id: str
    label: str
    href: str
    html: str
    status_code: int = 200
    parent_section: str = ""


@dataclass
class CrawlResult:
    """Results of crawling an IBM docs version."""

    version: str
    product_id: str
    pages: list[CrawledPage] = field(default_factory=list)
    failed_hrefs: list[str] = field(default_factory=list)
    total_topics: int = 0
    skipped_topics: int = 0


def _get_product_id(version: str) -> str:
    """Get IBM product ID for a version (e.g., SSEG27_8.1)."""
    ver_info = IBM_VERSIONS.get(version)
    if not ver_info:
        raise ValueError(
            f"Unknown IBM version: {version}. Available: {list(IBM_VERSIONS.keys())}"
        )
    return ver_info["product_id"]


def _fetch_with_retry(
    client: httpx.Client, url: str, retries: int = MAX_RETRIES
) -> tuple[str, int]:
    """Fetch a URL with retries and backoff."""
    for attempt in range(retries):
        try:
            resp = client.get(url, follow_redirects=True)
            if resp.status_code == 200:
                return resp.text, 200
            if resp.status_code == 429:
                wait = (attempt + 1) * 5
                logger.warning("Rate limited, waiting %ds: %s", wait, url)
                time.sleep(wait)
                continue
            if resp.status_code >= 500:
                time.sleep(2)
                continue
            return "", resp.status_code
        except httpx.TimeoutException:
            logger.warning("Timeout (attempt %d/%d): %s", attempt + 1, retries, url)
            time.sleep(2)
        except httpx.HTTPError as exc:
            logger.warning("HTTP error: %s - %s", url, exc)
            time.sleep(2)
    return "", 0


def _flatten_toc(
    topics: list[dict],
    depth: int = 0,
    parent_label: str = "",
) -> list[TocEntry]:
    """Recursively flatten the TOC tree into a list of entries."""
    entries: list[TocEntry] = []
    for topic in topics:
        topic_id = topic.get("topicId", "")
        label = topic.get("label", "")
        href = topic.get("href", "")

        if topic_id and href:
            entries.append(TocEntry(
                topic_id=topic_id,
                label=label,
                href=href,
                depth=depth,
                parent_label=parent_label,
            ))

        if "topics" in topic:
            entries.extend(_flatten_toc(
                topic["topics"],
                depth=depth + 1,
                parent_label=label or parent_label,
            ))

    return entries


def fetch_toc(version: str) -> list[TocEntry]:
    """Fetch the full table of contents for an IBM Storage Ceph version.

    Uses the IBM docs TOC API endpoint.
    """
    product_id = _get_product_id(version)
    toc_url = f"{IBM_DOCS_API_BASE}/toc/{product_id}"
    logger.info("Fetching TOC from %s", toc_url)

    with httpx.Client(
        timeout=REQUEST_TIMEOUT, headers=_HEADERS, follow_redirects=True
    ) as client:
        text, status = _fetch_with_retry(client, toc_url)

    if not text:
        raise RuntimeError(f"Failed to fetch TOC: {toc_url} (status={status})")

    import json
    data = json.loads(text)
    toc = data.get("toc", {})
    topics = toc.get("topics", [])

    entries = _flatten_toc(topics)
    logger.info("TOC contains %d total entries for %s", len(entries), version)
    return entries


def _should_skip_topic(entry: TocEntry) -> bool:
    """Determine if a topic should be skipped."""
    if entry.topic_id in _SKIP_TOPIC_IDS:
        return True
    # Skip z-stream bug-fix / known-issue dumps. Keep enhancement pages
    # (e.g. 9.1z1 CephX aes256k) so they land in the index.
    if "release-notes" in entry.href and entry.depth >= 2:
        href = entry.href.lower()
        if "enhancement" in href:
            return False
        return True
    return False


def _make_topic_url(topic_id: str, version: str) -> str:
    """Build the user-facing URL for a topic."""
    ver_info = IBM_VERSIONS[version]
    return f"{IBM_DOCS_BASE_URL}/{ver_info['url_version']}?topic={topic_id}"


def crawl_version(
    version: str,
    toc_entries: list[TocEntry] | None = None,
    throttle: float = THROTTLE_SECONDS,
    max_pages: int | None = None,
    skip_release_notes_details: bool = True,
) -> CrawlResult:
    """Crawl all topic pages for a given IBM docs version via the content API.

    Args:
        version: IBM version string (e.g., "8.1")
        toc_entries: Pre-fetched TOC (if None, fetches automatically)
        throttle: Seconds between requests
        max_pages: Optional cap on pages to fetch (for testing)
        skip_release_notes_details: Skip per-z-stream release note sub-pages

    Returns:
        CrawlResult with all fetched pages and failure info.
    """
    product_id = _get_product_id(version)

    if toc_entries is None:
        toc_entries = fetch_toc(version)

    # Filter topics
    filtered: list[TocEntry] = []
    skipped = 0
    for entry in toc_entries:
        if _should_skip_topic(entry):
            skipped += 1
            continue
        filtered.append(entry)

    if max_pages:
        filtered = filtered[:max_pages]

    result = CrawlResult(
        version=version,
        product_id=product_id,
        total_topics=len(toc_entries),
        skipped_topics=skipped,
    )

    logger.info(
        "Crawling %d pages for IBM Storage Ceph %s (%d skipped)",
        len(filtered), version, skipped,
    )

    with httpx.Client(
        timeout=REQUEST_TIMEOUT, headers=_HEADERS, follow_redirects=True
    ) as client:
        for i, entry in enumerate(filtered, 1):
            content_url = f"{IBM_DOCS_API_BASE}/content/{entry.href}"

            if i % 50 == 0 or i == 1:
                logger.info("[%d/%d] Fetching: %s", i, len(filtered), entry.label)

            html, status = _fetch_with_retry(client, content_url)

            if html and status == 200:
                page = CrawledPage(
                    url=_make_topic_url(entry.topic_id, version),
                    topic_id=entry.topic_id,
                    label=entry.label,
                    href=entry.href,
                    html=html,
                    status_code=status,
                    parent_section=entry.parent_label,
                )
                result.pages.append(page)
            else:
                logger.debug("Failed (%d): %s", status, entry.href)
                result.failed_hrefs.append(entry.href)

            if i < len(filtered):
                time.sleep(throttle)

    logger.info(
        "Crawl complete: %d fetched, %d failed out of %d topics",
        len(result.pages), len(result.failed_hrefs), len(filtered),
    )
    return result
