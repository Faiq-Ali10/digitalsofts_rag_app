"""Document parser interface and implementations.

Each parser extracts text content and metadata from a specific
file format. Parsers are registered by DocumentType and selected
automatically during ingestion.
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParsedDocument:
    """Result of parsing a document."""

    content: str
    metadata: dict[str, str] = field(default_factory=dict)
    sections: list[dict[str, str]] = field(default_factory=list)

    @property
    def content_hash(self) -> str:
        """SHA-256 hash of the document content for deduplication."""
        return hashlib.sha256(self.content.encode()).hexdigest()

    @property
    def is_empty(self) -> bool:
        return len(self.content.strip()) == 0


class DocumentParser(ABC):
    """Abstract base for document parsers."""

    @abstractmethod
    def parse(self, file_path: str | Path) -> ParsedDocument:
        """Parse a file and return extracted content with metadata."""
        ...

    @abstractmethod
    def parse_bytes(self, content: bytes, filename: str) -> ParsedDocument:
        """Parse raw bytes (e.g., from an upload)."""
        ...

    @staticmethod
    def clean_text(text: str) -> str:
        """Normalize whitespace and clean extracted text.
        Also performs light sanitization for indirect prompt injection attempts
        without corrupting legitimate enterprise documentation.
        """
        # Strip blatant instruction overrides that might be hidden in docs
        injection_patterns = [
            r"(?i)(?:ignore|disregard)\s+(?:all\s+)?(?:previous\s+)?(?:instructions|rules|directions)",
            r"(?i)you\s+are\s+now\s+(?:configured|programmed|instructed|an\s+administrator)",
            r"(?i)system\s+(?:prompt\s+)?override",
            r"(?i)forget\s+(?:all\s+)?(?:your\s+)?(?:system\s+)?prompt",
        ]

        for pattern in injection_patterns:
            text = re.sub(pattern, "[REDACTED_SYSTEM_OVERRIDE]", text)

        # Collapse multiple newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Collapse multiple spaces
        text = re.sub(r"[ \t]{2,}", " ", text)
        # Strip leading/trailing whitespace per line
        lines = [line.strip() for line in text.split("\n")]
        return "\n".join(lines).strip()
