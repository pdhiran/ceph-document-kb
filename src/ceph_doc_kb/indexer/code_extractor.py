"""Extract code blocks from RST content into a searchable index."""

from __future__ import annotations

import re
from pathlib import Path
from ceph_doc_kb.models import CodeExample

CEPH_COMMAND_PATTERN = re.compile(
    r'\b(ceph\s+[\w\-\s]+|rbd\s+[\w\-\s]+|rados\s+[\w\-\s]+|'
    r'cephadm\s+[\w\-\s]+|radosgw-admin\s+[\w\-\s]+)\b'
)

CODE_BLOCK_RST = re.compile(
    r'\.\.\s+code-block::\s*(\w*)\s*\n'
    r'(?:\s+:[\w-]+:.*\n)*'  # optional directive options
    r'\s*\n'
    r'((?:[ \t]+\S.*\n?)+)',  # indented content
    re.MULTILINE
)

LITERAL_BLOCK = re.compile(
    r'::\s*\n\s*\n((?:[ \t]+\S.*\n?)+)',
    re.MULTILINE
)


def _detect_language(code: str, declared: str) -> str:
    if declared:
        return declared
    if re.search(r'^\s*\$\s+', code, re.MULTILINE):
        return "bash"
    if re.search(r'^\s*{', code) and re.search(r'}\s*$', code, re.MULTILINE):
        return "json"
    if re.search(r'^\w+\s*=', code, re.MULTILINE):
        return "ini"
    return "text"


def _extract_commands(code: str) -> list[str]:
    """Extract Ceph commands from code block text."""
    commands = set()
    for match in CEPH_COMMAND_PATTERN.finditer(code):
        cmd = match.group(1).strip()
        cmd = re.sub(r'\s+', ' ', cmd)
        parts = cmd.split()
        if len(parts) >= 2:
            commands.add(' '.join(parts[:min(4, len(parts))]))
    return sorted(commands)


def _get_context(content: str, match_start: int, context_chars: int = 200) -> str:
    """Get surrounding paragraph text as context for a code block."""
    before_start = max(0, match_start - context_chars)
    before_text = content[before_start:match_start]
    paragraphs = before_text.split('\n\n')
    if paragraphs:
        return paragraphs[-1].strip()
    return ""


def extract_code_blocks(
    content: str,
    source_file: str,
    component: str,
    section_title: str = "",
) -> list[CodeExample]:
    """Extract all code blocks from RST content."""
    examples = []

    for match in CODE_BLOCK_RST.finditer(content):
        declared_lang = match.group(1).strip()
        raw_code = match.group(2)
        code = _dedent_block(raw_code)
        if not code.strip():
            continue

        language = _detect_language(code, declared_lang)
        context = _get_context(content, match.start())
        commands = _extract_commands(code)

        example = CodeExample(
            entity_id=CodeExample.make_id(source_file, code),
            code=code.strip(),
            language=language,
            context=context,
            source_file=source_file,
            component=component,
            section_title=section_title,
            commands_used=commands,
        )
        examples.append(example)

    for match in LITERAL_BLOCK.finditer(content):
        raw_code = match.group(1)
        code = _dedent_block(raw_code)
        if not code.strip() or len(code.strip()) < 10:
            continue

        language = _detect_language(code, "")
        context = _get_context(content, match.start())
        commands = _extract_commands(code)

        example = CodeExample(
            entity_id=CodeExample.make_id(source_file, code),
            code=code.strip(),
            language=language,
            context=context,
            source_file=source_file,
            component=component,
            section_title=section_title,
            commands_used=commands,
        )
        examples.append(example)

    return examples


def _dedent_block(text: str) -> str:
    """Remove common leading whitespace from a block of text."""
    lines = text.split('\n')
    non_empty = [l for l in lines if l.strip()]
    if not non_empty:
        return text
    min_indent = min(len(l) - len(l.lstrip()) for l in non_empty)
    return '\n'.join(l[min_indent:] if len(l) >= min_indent else l for l in lines)


def extract_from_file(file_path: Path, docs_root: Path) -> list[CodeExample]:
    """Extract code examples from a single RST file."""
    try:
        content = file_path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return []

    rel_path = str(file_path.relative_to(docs_root))
    parts = rel_path.split('/')
    component = parts[0] if parts else "other"

    return extract_code_blocks(content, rel_path, component)
