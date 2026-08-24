"""Plain text document parser.

Simple parser for .txt files with paragraph-based section detection.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from app.ingestion.parsers.base import DocumentParser, ParsedDocument

logger = structlog.get_logger(__name__)


class TextParser(DocumentParser):
    """Parse plain text files."""

    def parse(self, file_path: str | Path) -> ParsedDocument:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Text file not found: {path}")

        content = path.read_text(encoding="utf-8", errors="replace")
        return self._extract(content, path.name)

    def parse_bytes(self, content: bytes, filename: str) -> ParsedDocument:
        text = content.decode("utf-8", errors="replace")
        return self._extract(text, filename)

    def _extract(self, text: str, filename: str) -> ParsedDocument:
        cleaned = self.clean_text(text)

        # Split into paragraph-based sections
        paragraphs = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
        sections = [
            {"content": p, "section": f"Paragraph {i + 1}"}
            for i, p in enumerate(paragraphs)
        ]

        if not sections:
            sections = [{"content": cleaned, "section": "Main"}]

        logger.info(
            "text_parsed",
            filename=filename,
            sections=len(sections),
            chars=len(cleaned),
        )

        return ParsedDocument(
            content=cleaned,
            metadata={"filename": filename},
            sections=sections,
        )
