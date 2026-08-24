"""PDF document parser using PyMuPDF (fitz).

Extracts text content page-by-page with page number metadata.
Handles corrupt PDFs gracefully.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from app.ingestion.parsers.base import DocumentParser, ParsedDocument

logger = structlog.get_logger(__name__)


class PDFParser(DocumentParser):
    """Parse PDF files using PyMuPDF."""

    def parse(self, file_path: str | Path) -> ParsedDocument:
        """Parse a PDF file from disk."""
        import fitz  # PyMuPDF

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {path}")

        try:
            doc = fitz.open(str(path))
        except Exception as e:
            logger.error("pdf_parse_failed", path=str(path), error=str(e))
            raise ValueError(f"Failed to open PDF: {e}") from e

        return self._extract(doc, path.name)

    def parse_bytes(self, content: bytes, filename: str) -> ParsedDocument:
        """Parse PDF from raw bytes."""
        import fitz

        try:
            doc = fitz.open(stream=content, filetype="pdf")
        except Exception as e:
            logger.error("pdf_parse_bytes_failed", filename=filename, error=str(e))
            raise ValueError(f"Failed to parse PDF bytes: {e}") from e

        return self._extract(doc, filename)

    def _extract(self, doc, filename: str) -> ParsedDocument:
        """Extract text and metadata from an open fitz document."""
        sections = []
        all_text = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            cleaned = self.clean_text(text)

            if cleaned:
                sections.append({
                    "content": cleaned,
                    "page": str(page_num + 1),
                    "section": f"Page {page_num + 1}",
                })
                all_text.append(cleaned)

        metadata = {
            "page_count": str(len(doc)),
            "filename": filename,
        }

        # Extract PDF metadata if available
        pdf_meta = doc.metadata
        if pdf_meta:
            if pdf_meta.get("title"):
                metadata["title"] = pdf_meta["title"]
            if pdf_meta.get("author"):
                metadata["author"] = pdf_meta["author"]

        doc.close()

        content = "\n\n".join(all_text)
        logger.info(
            "pdf_parsed",
            filename=filename,
            pages=len(sections),
            chars=len(content),
        )

        return ParsedDocument(
            content=content,
            metadata=metadata,
            sections=sections,
        )
