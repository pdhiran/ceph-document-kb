"""HTML parser for IBM Storage Ceph documentation pages.

Parses HTML fetched from ibm.com/docs into DocChunks using the same model
as the upstream RST parser. Handles IBM-specific markup patterns:
headings, code blocks, notes/important callouts, tables, and lists.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from ceph_doc_kb.constants import IBM_TOPIC_COMPONENT_MAP
from ceph_doc_kb.models import CodeExample, DocChunk

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 4000
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _detect_component_from_topic(topic_slug: str) -> str:
    """Map an IBM docs topic slug to a Ceph component."""
    slug_lower = topic_slug.lower()
    for pattern, component in IBM_TOPIC_COMPONENT_MAP.items():
        if pattern in slug_lower:
            return component
    return "general"


def _detect_topic_from_slug(topic_slug: str) -> str:
    """Extract a topic category from the slug."""
    parts = topic_slug.split("-")
    if len(parts) >= 2:
        return parts[0]
    return "general"


def _clean_text(text: str) -> str:
    """Normalize whitespace in extracted text."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def _extract_code_blocks(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Extract code blocks with their language hint."""
    blocks = []
    for pre in soup.find_all("pre"):
        code_tag = pre.find("code")
        text = code_tag.get_text() if code_tag else pre.get_text()
        text = text.strip()
        if not text:
            continue

        lang = ""
        if code_tag:
            classes = code_tag.get("class", [])
            for cls in classes:
                if cls.startswith("language-"):
                    lang = cls.replace("language-", "")
                    break
                if cls.startswith("hljs-"):
                    continue
                if cls not in ("code", "highlight"):
                    lang = cls
                    break
        blocks.append((text, lang))
    return blocks


def _render_element(element: Tag | NavigableString) -> str:
    """Recursively render an HTML element to readable markdown-ish text."""
    if isinstance(element, NavigableString):
        return str(element)

    if not isinstance(element, Tag):
        return ""

    tag = element.name

    if tag in ("script", "style", "nav", "footer", "header"):
        return ""

    if tag == "pre":
        code_tag = element.find("code")
        code_text = code_tag.get_text() if code_tag else element.get_text()
        lang = ""
        if code_tag:
            classes = code_tag.get("class", [])
            for cls in classes:
                if cls.startswith("language-"):
                    lang = cls.replace("language-", "")
                    break
        # IBM DITA uses <pre class="pre codeblock"> without nested <code>
        if not lang:
            pre_classes = element.get("class", [])
            if "codeblock" in pre_classes:
                lang = "bash"
        return f"\n```{lang}\n{code_text.strip()}\n```\n"

    if tag == "code":
        parent = element.parent
        if parent and parent.name == "pre":
            return ""
        return f"`{element.get_text()}`"

    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(tag[1])
        prefix = "#" * level
        return f"\n{prefix} {element.get_text().strip()}\n"

    if tag == "strong" or tag == "b":
        return f"**{element.get_text()}**"

    if tag == "em" or tag == "i":
        return f"*{element.get_text()}*"

    if tag == "a":
        text = element.get_text()
        href = element.get("href", "")
        if href and not href.startswith("#"):
            return f"{text}"
        return text

    if tag in ("ul", "ol"):
        items = []
        for i, li in enumerate(element.find_all("li", recursive=False), 1):
            li_text = _render_children(li).strip()
            prefix = f"{i}. " if tag == "ol" else "- "
            items.append(f"{prefix}{li_text}")
        return "\n" + "\n".join(items) + "\n"

    if tag == "table":
        return _render_table(element)

    if tag == "blockquote":
        inner = _render_children(element).strip()
        return f"\n> {inner}\n"

    if tag == "p":
        return "\n" + _render_children(element).strip() + "\n"

    if tag == "br":
        return "\n"

    if tag == "img":
        return ""

    # div with class note/important/warning
    classes = element.get("class", [])
    class_str = " ".join(classes).lower() if classes else ""
    if any(kw in class_str for kw in ("note", "important", "warning", "caution", "tip")):
        label = "Note"
        for kw in ("important", "warning", "caution", "tip"):
            if kw in class_str:
                label = kw.capitalize()
                break
        inner = _render_children(element).strip()
        return f"\n**{label}:** {inner}\n"

    return _render_children(element)


def _render_children(element: Tag) -> str:
    """Render all children of a tag."""
    parts = []
    for child in element.children:
        parts.append(_render_element(child))
    return "".join(parts)


def _render_table(table: Tag) -> str:
    """Render an HTML table as a markdown-style table."""
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells = []
        for td in tr.find_all(["td", "th"]):
            cells.append(td.get_text().strip().replace("\n", " "))
        if cells:
            rows.append(cells)

    if not rows:
        return table.get_text()

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


def _split_oversized(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split text exceeding max_chars on paragraph boundaries."""
    if len(text) <= max_chars:
        return [text]

    paragraphs = re.split(r"\n{2,}", text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current_len + para_len > max_chars and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(para)
        current_len += para_len + 2

    if current:
        chunks.append("\n\n".join(current))

    return chunks if chunks else [text]


def parse_ibm_page(
    html: str,
    url: str,
    topic_slug: str,
    version: str,
) -> list[DocChunk]:
    """Parse a single IBM documentation HTML page into DocChunks.

    Returns an empty list (never raises) if the page has insufficient content.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Remove navigation, footer, breadcrumbs, sentinel elements
    for selector in (
        "nav", "footer", "header", ".breadcrumb", ".bx--side-nav",
        "[class*='sentinel']", "[class*='feedback']", ".copyright",
        "[class*='toc']", "[class*='pagination']",
        ".familylinks", ".ulchildlink", ".relinfo",
    ):
        for el in soup.select(selector):
            el.decompose()

    # Find the main content area
    main = soup.find("main") or soup.find("article") or soup.find(
        "div", class_=re.compile(r"content|body|topic", re.I)
    )
    if not main:
        main = soup.body or soup

    # Extract the page title
    title_tag = main.find("h1")
    page_title = title_tag.get_text().strip() if title_tag else ""
    if not page_title:
        title_meta = soup.find("title")
        page_title = title_meta.get_text().strip() if title_meta else topic_slug

    # Remove " - IBM Documentation" suffix from title
    page_title = re.sub(r"\s*[-–]\s*IBM\s+Documentation\s*$", "", page_title)

    # Extract last updated date
    last_updated = ""
    updated_el = soup.find(string=re.compile(r"Last Updated:"))
    if updated_el:
        match = re.search(r"Last Updated:\s*(.+)", updated_el.get_text())
        if match:
            last_updated = match.group(1).strip()

    component = _detect_component_from_topic(topic_slug)
    topic = _detect_topic_from_slug(topic_slug)

    # Render the full content
    if title_tag:
        title_tag.decompose()

    content = _render_children(main)
    content = _clean_text(content)

    # Filter out pages with insufficient content
    content_no_boilerplate = re.sub(
        r"(?i)(while ibm values|© copyright|focus sentinel|copy to clipboard|"
        r"was this topic helpful|filter on titles|change version|"
        r"a newer version of this product)", "", content
    )
    if len(content_no_boilerplate.strip()) < 100:
        logger.debug("Skipping thin page: %s (%d chars)", topic_slug, len(content_no_boilerplate))
        return []

    # Split into sections by h2/h3 headings
    sections = _split_into_sections(content, page_title)

    chunks: list[DocChunk] = []
    source_file = f"ibm-docs/{version}/{topic_slug}"

    for sec in sections:
        sec_title = sec["title"]
        sec_content = sec["content"]
        sec_path = f"{page_title} > {sec_title}" if sec_title != page_title else page_title

        text_pieces = _split_oversized(sec_content)

        for idx, piece in enumerate(text_pieces):
            chunk_path = sec_path
            if len(text_pieces) > 1:
                chunk_path = f"{sec_path} (part {idx + 1})"

            entity_id = DocChunk.make_id(source_file, chunk_path)

            chunks.append(DocChunk(
                entity_id=entity_id,
                title=sec_title,
                content=piece.strip(),
                component=component,
                topic=topic,
                source_file=source_file,
                section_path=chunk_path,
                doc_url=url,
                commands_referenced=[],
                version=f"ibm-{version}",
                deprecated=False,
                version_added="",
                version_changed=last_updated,
                warnings=[],
                see_also=[],
            ))

    return chunks


def _split_into_sections(content: str, page_title: str) -> list[dict[str, str]]:
    """Split rendered content into sections by heading boundaries."""
    heading_re = re.compile(r"^(#{2,4})\s+(.+)$", re.MULTILINE)
    matches = list(heading_re.finditer(content))

    if not matches:
        return [{"title": page_title, "content": content}]

    sections: list[dict[str, str]] = []

    # Content before first heading
    pre_content = content[:matches[0].start()].strip()
    if pre_content:
        sections.append({"title": page_title, "content": pre_content})

    for i, match in enumerate(matches):
        title = match.group(2).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        if body:
            sections.append({"title": title, "content": body})

    return sections if sections else [{"title": page_title, "content": content}]


def extract_code_examples_from_page(
    html: str,
    topic_slug: str,
    version: str,
) -> list[CodeExample]:
    """Extract code examples from an IBM docs HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    component = _detect_component_from_topic(topic_slug)
    source_file = f"ibm-docs/{version}/{topic_slug}"

    # Find page title for context
    title_tag = soup.find("h1")
    page_title = title_tag.get_text().strip() if title_tag else topic_slug

    examples: list[CodeExample] = []
    for pre in soup.find_all("pre"):
        code_tag = pre.find("code")
        code_text = code_tag.get_text() if code_tag else pre.get_text()
        code_text = code_text.strip()
        if not code_text or len(code_text) < 10:
            continue

        lang = "bash"
        if code_tag:
            classes = code_tag.get("class", [])
            for cls in classes:
                if cls.startswith("language-"):
                    lang = cls.replace("language-", "")
                    break

        # Get surrounding context
        context_parts = []
        prev_sib = pre.find_previous_sibling(["p", "h2", "h3", "h4"])
        if prev_sib:
            context_parts.append(prev_sib.get_text().strip()[:200])

        context = " ".join(context_parts) if context_parts else page_title

        # Detect commands in the code
        from ceph_doc_kb.constants import COMMAND_WITH_SUBCOMMANDS_RE
        commands_used = []
        for match in COMMAND_WITH_SUBCOMMANDS_RE.finditer(code_text):
            cmd = (match.group(1) + match.group(2)).strip()
            commands_used.append(cmd)

        entity_id = CodeExample.make_id(source_file, code_text)
        examples.append(CodeExample(
            entity_id=entity_id,
            code=code_text,
            language=lang,
            context=context,
            source_file=source_file,
            component=component,
            section_title=page_title,
            commands_used=commands_used,
        ))

    return examples
