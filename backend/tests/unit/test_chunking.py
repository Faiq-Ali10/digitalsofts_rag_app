"""Unit tests for text chunking."""

from __future__ import annotations

import pytest

from app.ingestion.chunking import chunk_document, recursive_character_split


class TestRecursiveCharacterSplit:
    """Tests for the recursive splitter."""

    def test_short_text_not_split(self):
        """Text shorter than chunk_size should not be split."""
        text = "This is a short text."
        result = recursive_character_split(text, chunk_size=1000)
        assert len(result) == 1
        assert result[0] == text

    def test_long_text_split(self):
        """Long text should be split into multiple chunks."""
        text = "Word " * 500  # ~2500 chars
        result = recursive_character_split(text, chunk_size=500, chunk_overlap=50)
        assert len(result) > 1
        # Each chunk should be within size limit (roughly)
        for chunk in result:
            assert len(chunk) <= 600  # Allow some overflow from overlap

    def test_empty_text(self):
        """Empty text should return empty list."""
        result = recursive_character_split("", chunk_size=1000)
        assert result == []

    def test_respects_paragraph_boundaries(self):
        """Should prefer splitting on paragraph boundaries."""
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        result = recursive_character_split(text, chunk_size=30, chunk_overlap=0)
        # Should split on \n\n
        assert len(result) >= 2

    def test_whitespace_only(self):
        """Whitespace-only text should return empty list."""
        result = recursive_character_split("   \n\n   ", chunk_size=1000)
        assert result == []


class TestChunkDocument:
    """Tests for the document chunking function."""

    def test_chunk_with_sections(self):
        """Should chunk each section independently."""
        sections = [
            {"content": "Section A content " * 20, "section": "Section A"},
            {"content": "Section B content " * 20, "section": "Section B"},
        ]
        content = "\n\n".join(s["content"] for s in sections)

        chunks = chunk_document(
            content=content,
            base_metadata={"document_id": "test"},
            sections=sections,
            chunk_size=200,
            chunk_overlap=20,
        )

        assert len(chunks) > 2
        # All chunks should have section metadata
        for chunk in chunks:
            assert "section" in chunk.metadata
        # Sequential chunk indices
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_chunk_without_sections(self):
        """Should chunk the full document when no sections provided."""
        content = "Content block. " * 100

        chunks = chunk_document(
            content=content,
            base_metadata={"document_id": "test"},
            chunk_size=200,
            chunk_overlap=20,
        )

        assert len(chunks) > 1
        assert all(c.metadata.get("document_id") == "test" for c in chunks)

    def test_metadata_preserved(self):
        """Base metadata should be on every chunk."""
        meta = {"document_id": "123", "title": "Test", "product": "ERP"}
        chunks = chunk_document(
            content="A" * 500,
            base_metadata=meta,
            chunk_size=200,
        )

        for chunk in chunks:
            assert chunk.metadata["document_id"] == "123"
            assert chunk.metadata["title"] == "Test"

    def test_token_count_estimate(self):
        """Token count estimate should be reasonable."""
        chunks = chunk_document(
            content="Hello world. " * 50,
            base_metadata={},
            chunk_size=200,
        )

        for chunk in chunks:
            assert chunk.token_count_estimate > 0
            assert chunk.token_count_estimate < len(chunk.content)
