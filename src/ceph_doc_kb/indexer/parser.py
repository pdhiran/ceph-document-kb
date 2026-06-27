"""RST parser and chunker for the Ceph documentation knowledge base.

Parses RST files using docutils, chunks by section headings, preserves code
blocks and directives, extracts commands and metadata, and produces DocChunks
suitable for embedding and retrieval.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path, PurePosixPath
from typing import Any

import docutils.nodes as nodes
from docutils.frontend import get_default_settings
from docutils.parsers.rst import Directive, Parser as RSTParser, directives
from docutils.utils import new_document

from ceph_doc_kb.models import DocChunk

log = logging.getLogger(__name__)

CEPH_DOCS_BASE_URL = "https://docs.ceph.com/en/latest"
COMMAND_PATTERN = re.compile(
    r"\b(ceph-bluestore-tool|ceph-authtool|ceph-rbdnamer|ceph-volume"
    r"|ceph-fuse|ceph-mds|ceph-mgr|ceph-mon|ceph-osd"
    r"|radosgw-admin|rgw-orphan-list|rbd-mirror|rbd-nbd|mount\.ceph"
    r"|cephadm|crushtool|ceph|rados|rbd)(?=\s|$|[;|&,()'\"])"
)
APPROX_CHARS_PER_TOKEN = 4
TARGET_MAX_TOKENS = 1000
MAX_CHUNK_CHARS = TARGET_MAX_TOKENS * APPROX_CHARS_PER_TOKEN


# ---------------------------------------------------------------------------
# Register Sphinx-only directives so docutils doesn't discard them
# ---------------------------------------------------------------------------

class _VersionDirective(Directive):
    """Stub for versionadded / versionchanged / deprecated."""
    has_content = True
    required_arguments = 0
    optional_arguments = 1
    final_argument_whitespace = True
    option_spec: dict[str, Any] = {}

    def run(self) -> list[nodes.Node]:
        node = nodes.container()
        node["classes"].append(self.name)
        if self.arguments:
            node["version"] = self.arguments[0]
        self.state.nested_parse(self.content, self.content_offset, node)
        return [node]


class _SeeAlsoDirective(Directive):
    has_content = True
    required_arguments = 0
    optional_arguments = 0
    option_spec: dict[str, Any] = {}

    def run(self) -> list[nodes.Node]:
        node = nodes.container()
        node["classes"].append("seealso")
        self.state.nested_parse(self.content, self.content_offset, node)
        return [node]


class _ConfvalDirective(Directive):
    """Stub for Sphinx confval / option / describe directives."""
    has_content = True
    required_arguments = 0
    optional_arguments = 1
    final_argument_whitespace = True
    option_spec: dict[str, Any] = {}

    def run(self) -> list[nodes.Node]:
        node = nodes.container()
        node["classes"].append(self.name)
        if self.arguments:
            title_node = nodes.strong(text=self.arguments[0])
            node += title_node
        self.state.nested_parse(self.content, self.content_offset, node)
        return [node]


def _register_directives() -> None:
    for name in ("versionadded", "versionchanged", "deprecated"):
        directives.register_directive(name, _VersionDirective)
    directives.register_directive("seealso", _SeeAlsoDirective)
    for name in ("confval", "option", "describe", "glossary",
                 "toctree", "only", "highlight", "index",
                 "module", "currentmodule", "automodule",
                 "autoclass", "autofunction"):
        directives.register_directive(name, _ConfvalDirective)


_register_directives()


# ---------------------------------------------------------------------------
# Path / metadata helpers
# ---------------------------------------------------------------------------

def _detect_component_and_topic(rel_path: str) -> tuple[str, str]:
    """Derive component and topic from the relative file path.

    ``rados/operations/pools.rst`` -> component="rados", topic="operations"
    """
    parts = PurePosixPath(rel_path).parts
    if len(parts) >= 3:
        return parts[0], parts[1]
    if len(parts) == 2:
        return parts[0], "general"
    return "unknown", "general"


def _make_doc_url(rel_path: str) -> str:
    stem = str(PurePosixPath(rel_path).with_suffix(""))
    return f"{CEPH_DOCS_BASE_URL}/{stem}/"


def _rel_source(file_path: Path, docs_root: Path) -> str:
    """Return a POSIX-style relative path string, or the filename as fallback."""
    try:
        return str(
            PurePosixPath(file_path.resolve().relative_to(docs_root.resolve()))
        )
    except ValueError:
        return str(PurePosixPath(file_path.name))


# ---------------------------------------------------------------------------
# RST parsing
# ---------------------------------------------------------------------------

def _parse_rst(text: str) -> nodes.document:
    parser = RSTParser()
    settings = get_default_settings(RSTParser)
    settings.report_level = 5
    settings.halt_level = 5
    doc = new_document("<rst-doc>", settings)
    parser.parse(text, doc)
    return doc


# ---------------------------------------------------------------------------
# Docutils node -> text rendering
# ---------------------------------------------------------------------------

_ADMONITION_LABELS = {
    "note": "Note",
    "warning": "Warning",
    "important": "Important",
    "tip": "Tip",
    "hint": "Hint",
    "caution": "Caution",
    "danger": "Danger",
    "attention": "Attention",
    "error": "Error",
}


def _render_node(node: nodes.Node) -> str:
    """Recursively render a docutils node back to readable text.

    Preserves code blocks verbatim; admonitions get a label prefix.
    """
    if isinstance(node, nodes.Text):
        return node.astext()

    if isinstance(node, (nodes.comment, nodes.substitution_definition,
                         nodes.target, nodes.footnote, nodes.system_message)):
        return ""

    if isinstance(node, nodes.literal_block):
        lang = _code_block_lang(node)
        code = node.astext()
        if lang:
            return f"\n```{lang}\n{code}\n```\n"
        return f"\n```\n{code}\n```\n"

    if isinstance(node, nodes.literal):
        return f"`{node.astext()}`"

    if isinstance(node, (nodes.strong, nodes.rubric)):
        return f"**{node.astext()}**"

    if isinstance(node, nodes.emphasis):
        return f"*{node.astext()}*"

    if isinstance(node, (nodes.reference, nodes.title_reference)):
        return node.astext()

    if isinstance(node, nodes.substitution_reference):
        return node.astext()

    if isinstance(node, nodes.image):
        return ""

    if isinstance(node, nodes.raw):
        return ""

    if isinstance(node, nodes.Element):
        tag = node.tagname

        if tag in _ADMONITION_LABELS:
            body = _render_children(node)
            return f"\n**{_ADMONITION_LABELS[tag]}:** {body.strip()}\n"

        if tag in ("bullet_list", "enumerated_list"):
            return _render_list(node)

        if tag == "definition_list":
            return _render_definition_list(node)

        if tag == "block_quote":
            body = _render_children(node)
            return "\n" + body.strip() + "\n"

        if tag == "line_block":
            return "\n".join(_render_node(c) for c in node.children) + "\n"

        if tag == "table":
            return _render_table_simple(node)

        if tag == "title":
            return ""

        return _render_children(node)

    return node.astext() if hasattr(node, "astext") else ""


def _code_block_lang(node: nodes.literal_block) -> str:
    lang = node.get("language", "")
    if lang:
        return lang
    classes = node.get("classes", [])
    for cls in classes:
        if cls not in ("code",):
            return cls
    return ""


def _render_children(node: nodes.Element) -> str:
    return "".join(_render_node(child) for child in node.children)


def _render_list(node: nodes.Element) -> str:
    items: list[str] = []
    is_ordered = isinstance(node, nodes.enumerated_list)
    for i, item in enumerate(node.children, 1):
        text = _render_children(item).strip()
        prefix = f"{i}. " if is_ordered else "- "
        items.append(f"{prefix}{text}")
    return "\n" + "\n".join(items) + "\n"


def _render_definition_list(node: nodes.Element) -> str:
    parts: list[str] = []
    for item in node.children:
        if not hasattr(item, "tagname") or item.tagname != "definition_list_item":
            continue
        term = ""
        defn = ""
        for child in item.children:
            if child.tagname == "term":
                term = child.astext()
            elif child.tagname == "definition":
                defn = _render_children(child).strip()
        parts.append(f"**{term}**: {defn}")
    return "\n" + "\n".join(parts) + "\n"


def _render_table_simple(node: nodes.Element) -> str:
    """Best-effort plain-text table rendering."""
    rows: list[list[str]] = []
    for row_node in node.findall(condition=lambda n: getattr(n, "tagname", "") == "row"):
        cells = [
            entry.astext().replace("\n", " ").strip()
            for entry in row_node.children
            if hasattr(entry, "tagname") and entry.tagname == "entry"
        ]
        if cells:
            rows.append(cells)
    if not rows:
        return node.astext()
    col_count = max(len(r) for r in rows)
    for r in rows:
        while len(r) < col_count:
            r.append("")
    widths = [max(len(r[c]) for r in rows) for c in range(col_count)]
    lines: list[str] = []
    for i, row in enumerate(rows):
        line = "| " + " | ".join(
            cell.ljust(widths[j]) for j, cell in enumerate(row)
        ) + " |"
        lines.append(line)
        if i == 0:
            lines.append("| " + " | ".join("-" * w for w in widths) + " |")
    return "\n" + "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Section / directive metadata extraction
# ---------------------------------------------------------------------------

class _SectionMeta:
    """Metadata accumulated while walking a section subtree."""

    __slots__ = (
        "warnings", "deprecated", "version_added", "version_changed",
        "see_also", "code_blocks",
    )

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.deprecated: bool = False
        self.version_added: str = ""
        self.version_changed: str = ""
        self.see_also: list[str] = []
        self.code_blocks: list[str] = []


def _extract_section_meta(node: nodes.Element) -> _SectionMeta:
    """Walk *node* (non-recursing into child sections) and collect metadata."""
    meta = _SectionMeta()
    for child in node.children:
        if isinstance(child, nodes.section):
            continue
        _collect_meta(child, meta)
    return meta


def _collect_meta(node: nodes.Node, meta: _SectionMeta) -> None:
    if isinstance(node, nodes.literal_block):
        meta.code_blocks.append(node.astext())
        return

    if not isinstance(node, nodes.Element):
        return

    tag = node.tagname
    classes = node.get("classes", [])

    if tag == "warning":
        meta.warnings.append(node.astext().strip())

    if tag == "container" or tag == "paragraph":
        if "deprecated" in classes:
            meta.deprecated = True
            ver = node.get("version", "")
            if not ver:
                ver = node.astext().strip()[:60]
            if ver:
                meta.version_changed = ver
        if "versionadded" in classes:
            meta.version_added = node.get("version", node.astext().strip()[:60])
        if "versionchanged" in classes:
            meta.version_changed = node.get("version", node.astext().strip()[:60])
        if "seealso" in classes:
            meta.see_also.extend(
                line.strip()
                for line in node.astext().strip().splitlines()
                if line.strip()
            )

    for child in node.children:
        if isinstance(child, nodes.section):
            continue
        _collect_meta(child, meta)


def _extract_commands(code_blocks: list[str]) -> list[str]:
    """Extract unique Ceph CLI commands referenced across code blocks."""
    found: set[str] = set()
    for block in code_blocks:
        for match in COMMAND_PATTERN.finditer(block):
            found.add(match.group(0))
    return sorted(found)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _split_oversized(
    text: str, max_chars: int = MAX_CHUNK_CHARS
) -> list[str]:
    """Split text exceeding *max_chars* on paragraph boundaries.

    Code blocks (``` ... ```) are never broken mid-block.  Falls back to
    sentence-level splitting for single paragraphs that exceed the limit.
    """
    if len(text) <= max_chars:
        return [text]

    code_block_re = re.compile(r"(```[^\n]*\n.*?\n```)", re.DOTALL)
    segments = code_block_re.split(text)

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def _flush() -> None:
        nonlocal current_len
        if current:
            chunks.append("".join(current))
            current.clear()
            current_len = 0

    for segment in segments:
        seg_len = len(segment)
        if code_block_re.match(segment):
            if current_len + seg_len > max_chars and current:
                _flush()
            current.append(segment)
            current_len += seg_len
        else:
            paragraphs = re.split(r"\n{2,}", segment)
            for para in paragraphs:
                para_len = len(para)
                if para_len > max_chars and not current:
                    # Single paragraph exceeds limit — split on sentences.
                    for sub in _split_on_sentences(para, max_chars):
                        chunks.append(sub)
                    continue
                if current_len + para_len > max_chars and current:
                    _flush()
                current.append(para + "\n\n")
                current_len += para_len + 2

    _flush()
    return chunks if chunks else [text]


def _split_on_sentences(text: str, max_chars: int) -> list[str]:
    """Last-resort split for a single block of text with no paragraph breaks."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sent in sentences:
        sent_len = len(sent)
        if current_len + sent_len > max_chars and current:
            chunks.append(" ".join(current))
            current.clear()
            current_len = 0
        current.append(sent)
        current_len += sent_len + 1

    if current:
        chunks.append(" ".join(current))
    return chunks if chunks else [text]


def _section_title(sec: nodes.Element) -> str:
    for child in sec.children:
        if isinstance(child, nodes.title):
            return child.astext()
    return ""


def _walk_sections(
    node: nodes.Element,
    *,
    depth: int = 0,
    parent_path: str = "",
) -> list[dict[str, Any]]:
    """Recursively collect sections with rendered content and metadata.

    Returns a flat list of dicts, each representing one potential chunk.
    """
    results: list[dict[str, Any]] = []

    for child in node.children:
        if not isinstance(child, nodes.section):
            continue

        sec_title = _section_title(child)
        sec_path = f"{parent_path} > {sec_title}" if parent_path else sec_title

        content_parts: list[str] = []
        for grandchild in child.children:
            if isinstance(grandchild, (nodes.section, nodes.title)):
                continue
            content_parts.append(_render_node(grandchild))
        body = "".join(content_parts).strip()

        meta = _extract_section_meta(child)

        if body:
            results.append({
                "title": sec_title,
                "section_path": sec_path,
                "content": body,
                "depth": depth + 1,
                "meta": meta,
            })

        results.extend(
            _walk_sections(child, depth=depth + 1, parent_path=sec_path)
        )

    return results


def _build_chunks_for_file(
    doc: nodes.document,
    source_file: str,
    version: str,
) -> list[DocChunk]:
    component, file_topic = _detect_component_and_topic(source_file)
    doc_url = _make_doc_url(source_file)

    sections = _walk_sections(doc)

    if not sections:
        body = _render_children(doc).strip()
        if not body:
            return []
        meta = _extract_section_meta(doc)
        doc_title = ""
        for child in doc.children:
            if isinstance(child, nodes.title):
                doc_title = child.astext()
                break
        if not doc_title:
            doc_title = (
                Path(source_file).stem.replace("-", " ").replace("_", " ").title()
            )
        sec_path = doc_title
        entity_id = DocChunk.make_id(source_file, sec_path)
        return [DocChunk(
            entity_id=entity_id,
            title=doc_title,
            content=body,
            component=component,
            topic=file_topic,
            source_file=source_file,
            section_path=sec_path,
            doc_url=doc_url,
            commands_referenced=_extract_commands(meta.code_blocks),
            version=version,
            deprecated=meta.deprecated,
            version_added=meta.version_added,
            version_changed=meta.version_changed,
            warnings=meta.warnings,
            see_also=meta.see_also,
        )]

    chunks: list[DocChunk] = []

    for sec in sections:
        sec_content: str = sec["content"]
        meta: _SectionMeta = sec["meta"]
        commands = _extract_commands(meta.code_blocks)

        text_pieces = _split_oversized(sec_content)

        for idx, piece in enumerate(text_pieces):
            sec_path = sec["section_path"]
            if len(text_pieces) > 1:
                sec_path = f"{sec_path} (part {idx + 1})"

            entity_id = DocChunk.make_id(source_file, sec_path)

            chunks.append(DocChunk(
                entity_id=entity_id,
                title=sec["title"],
                content=piece.strip(),
                component=component,
                topic=file_topic,
                source_file=source_file,
                section_path=sec_path,
                doc_url=doc_url,
                commands_referenced=commands,
                version=version,
                deprecated=meta.deprecated,
                version_added=meta.version_added,
                version_changed=meta.version_changed,
                warnings=meta.warnings,
                see_also=meta.see_also,
            ))

    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_rst_file(
    file_path: Path, docs_root: Path, version: str = ""
) -> list[DocChunk]:
    """Parse a single RST file into DocChunks.

    Returns an empty list (never raises) if the file cannot be parsed.
    """
    file_path = Path(file_path)
    docs_root = Path(docs_root)

    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("Cannot read %s: %s", file_path, exc)
        return []

    try:
        doc = _parse_rst(text)
    except Exception:
        log.warning("Failed to parse RST: %s", file_path, exc_info=True)
        return []

    source_rel = _rel_source(file_path, docs_root)

    try:
        return _build_chunks_for_file(doc, source_rel, version)
    except Exception:
        log.warning("Failed to chunk %s", file_path, exc_info=True)
        return []


def parse_docs_directory(
    docs_root: Path, version: str = ""
) -> list[DocChunk]:
    """Parse every ``*.rst`` file under *docs_root* into DocChunks.

    Unparseable files are skipped with a warning log.
    """
    docs_root = Path(docs_root)
    all_chunks: list[DocChunk] = []
    rst_files = sorted(docs_root.rglob("*.rst"))

    log.info("Scanning %d RST files under %s", len(rst_files), docs_root)

    for rst_file in rst_files:
        chunks = parse_rst_file(rst_file, docs_root, version=version)
        all_chunks.extend(chunks)

    log.info(
        "Parsed %d chunks from %d files", len(all_chunks), len(rst_files)
    )
    return all_chunks
