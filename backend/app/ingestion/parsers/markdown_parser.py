"""Markdown document parser.

Extracts text content with header-based section splitting
for improved chunking quality.
"""

from __future__ import annotations

import re
from pathlib import Path

import structlog

from app.ingestion.parsers.base import DocumentParser, ParsedDocument

logger = structlog.get_logger(__name__)


class MarkdownParser(DocumentParser):
    """Parse Markdown files with header-aware section extraction."""

    def parse(self, file_path: str | Path) -> ParsedDocument:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Markdown file not found: {path}")

        content = path.read_text(encoding="utf-8")
        return self._extract(content, path.name)

    def parse_bytes(self, content: bytes, filename: str) -> ParsedDocument:
        text = content.decode("utf-8", errors="replace")
        return self._extract(text, filename)

    def _extract(self, text: str, filename: str) -> ParsedDocument:
        """Extract content and split by headers."""
        cleaned = self.clean_text(text)
        sections = self._split_by_headers(cleaned)

        # Extract title from first H1
        title_match = re.search(r"^#\s+(.+)$", cleaned, re.MULTILINE)
        metadata = {
            "filename": filename,
        }
        if title_match:
            metadata["title"] = title_match.group(1).strip()

        logger.info(
            "markdown_parsed",
            filename=filename,
            sections=len(sections),
            chars=len(cleaned),
        )

        return ParsedDocument(
            content=cleaned,
            metadata=metadata,
            sections=sections,
        )

    @staticmethod
    def _split_by_headers(text: str) -> list[dict[str, str]]:
        """Split markdown text into sections based on headers.

        Each section includes the header and all content until the next
        header of equal or higher level.
        """
        # Match markdown headers (# through ####)
        header_pattern = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
        matches = list(header_pattern.finditer(text))

        if not matches:
            return [{"content": text, "section": "Main"}]

        sections = []

        # Content before first header
        pre_header = text[: matches[0].start()].strip()
        if pre_header:
            sections.append({"content": pre_header, "section": "Introduction"})

        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)

            section_content = text[start:end].strip()
            section_title = match.group(2).strip()

            if section_content:
                sections.append({
                    "content": section_content,
                    "section": section_title,
                    "level": str(len(match.group(1))),
                })

        return sections
