"""HTML document parser using BeautifulSoup.

Strips tags, extracts readable text, and preserves structural metadata.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from bs4 import BeautifulSoup

from app.ingestion.parsers.base import DocumentParser, ParsedDocument

logger = structlog.get_logger(__name__)


class HTMLParser(DocumentParser):
    """Parse HTML files by extracting text content."""

    # Tags to remove entirely (not just their content)
    REMOVE_TAGS = {"script", "style", "nav", "footer", "header", "aside", "noscript"}

    def parse(self, file_path: str | Path) -> ParsedDocument:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"HTML file not found: {path}")

        content = path.read_text(encoding="utf-8", errors="replace")
        return self._extract(content, path.name)

    def parse_bytes(self, content: bytes, filename: str) -> ParsedDocument:
        text = content.decode("utf-8", errors="replace")
        return self._extract(text, filename)

    def _extract(self, html: str, filename: str) -> ParsedDocument:
        soup = BeautifulSoup(html, "html.parser")

        # Remove non-content tags
        for tag in soup.find_all(self.REMOVE_TAGS):
            tag.decompose()

        # Extract metadata
        metadata = {"filename": filename}
        title_tag = soup.find("title")
        if title_tag:
            metadata["title"] = title_tag.get_text(strip=True)

        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            metadata["description"] = meta_desc["content"]

        # Extract sections from headings
        sections = []
        for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
            section_title = heading.get_text(strip=True)
            # Collect text until next heading
            content_parts = []
            for sibling in heading.find_next_siblings():
                if sibling.name in {"h1", "h2", "h3", "h4"}:
                    break
                text = sibling.get_text(separator=" ", strip=True)
                if text:
                    content_parts.append(text)

            if content_parts:
                sections.append(
                    {
                        "content": f"{section_title}\n\n" + "\n".join(content_parts),
                        "section": section_title,
                        "level": heading.name[1],
                    }
                )

        # Full text extraction
        text = soup.get_text(separator="\n", strip=True)
        cleaned = self.clean_text(text)

        if not sections and cleaned:
            sections = [{"content": cleaned, "section": "Main"}]

        logger.info(
            "html_parsed",
            filename=filename,
            sections=len(sections),
            chars=len(cleaned),
        )

        return ParsedDocument(
            content=cleaned,
            metadata=metadata,
            sections=sections,
        )
