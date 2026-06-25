"""Data models for the Ceph documentation knowledge base."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class DocChunk:
    """A single section/chunk of documentation."""

    entity_id: str
    title: str
    content: str
    component: str
    topic: str
    source_file: str
    section_path: str
    doc_url: str
    commands_referenced: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    version: str = ""
    quality_score: float = 0.5
    deprecated: bool = False
    version_added: str = ""
    version_changed: str = ""
    warnings: list[str] = field(default_factory=list)
    see_also: list[str] = field(default_factory=list)

    @staticmethod
    def make_id(source_file: str, section_path: str) -> str:
        raw = f"{source_file}::{section_path}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocChunk:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class CodeExample:
    """An extracted code block from documentation."""

    entity_id: str
    code: str
    language: str
    context: str
    source_file: str
    component: str
    section_title: str
    commands_used: list[str] = field(default_factory=list)

    @staticmethod
    def make_id(source_file: str, code: str) -> str:
        raw = f"{source_file}::{code[:100]}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CodeExample:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ComponentIndex:
    """Metadata for a component's index."""

    name: str
    chunk_count: int = 0
    code_example_count: int = 0
    topics: list[str] = field(default_factory=list)
    faiss_index_path: str = ""
    chunks_path: str = ""
    code_examples_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComponentIndex:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class IndexMetadata:
    """Top-level metadata for the full knowledge base index."""

    version: str
    ceph_version: str
    embedding_model: str
    embedding_dimensions: int
    total_chunks: int = 0
    total_code_examples: int = 0
    components: dict[str, ComponentIndex] = field(default_factory=dict)
    build_timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["components"] = {k: v.to_dict() if isinstance(v, ComponentIndex) else v
                          for k, v in self.components.items()}
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IndexMetadata:
        components = {
            k: ComponentIndex.from_dict(v) if isinstance(v, dict) else v
            for k, v in data.get("components", {}).items()
        }
        return cls(
            version=data["version"],
            ceph_version=data["ceph_version"],
            embedding_model=data["embedding_model"],
            embedding_dimensions=data["embedding_dimensions"],
            total_chunks=data.get("total_chunks", 0),
            total_code_examples=data.get("total_code_examples", 0),
            components=components,
            build_timestamp=data.get("build_timestamp", ""),
        )

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path) -> IndexMetadata:
        return cls.from_dict(json.loads(path.read_text()))


@dataclass
class SearchResult:
    """A single search result returned to the caller."""

    chunk: DocChunk
    score: float
    source: str  # "bm25" or "semantic" or "merged"

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.chunk.entity_id,
            "title": self.chunk.title,
            "content": self.chunk.content,
            "component": self.chunk.component,
            "topic": self.chunk.topic,
            "source_file": self.chunk.source_file,
            "section_path": self.chunk.section_path,
            "doc_url": self.chunk.doc_url,
            "commands_referenced": self.chunk.commands_referenced,
            "quality_score": self.chunk.quality_score,
            "score": self.score,
            "search_source": self.source,
            "deprecated": self.chunk.deprecated,
        }
