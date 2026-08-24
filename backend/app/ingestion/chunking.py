"""Text chunking strategies for document ingestion.

Uses recursive character splitting with configurable chunk size
and overlap. Supports header-aware splitting for structured documents.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings

settings = get_settings()


@dataclass
class TextChunk:
    """A chunk of text with its position metadata."""

    content: str
    chunk_index: int
    metadata: dict[str, str]

    @property
    def token_count_estimate(self) -> int:
        """Rough token estimate (1 token ≈ 4 chars for English)."""
        return len(self.content) // 4


def recursive_character_split(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    separators: list[str] | None = None,
) -> list[str]:
    """Split text recursively by trying separators in order.

    Tries to split on paragraph boundaries first, then sentences,
    then words, to keep semantically coherent chunks.

    Args:
        text: Text to split.
        chunk_size: Maximum characters per chunk.
        chunk_overlap: Overlap between consecutive chunks.
        separators: List of separators to try in order.

    Returns:
        List of text chunks.
    """
    chunk_size = chunk_size or settings.rag_chunk_size
    chunk_overlap = chunk_overlap or settings.rag_chunk_overlap
    separators = separators or ["\n\n", "\n", ". ", " ", ""]

    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    # Find the best separator that creates chunks of reasonable size
    for sep in separators:
        if sep == "":
            # Last resort: character-level split
            step = max(1, chunk_size - chunk_overlap)
            splits = [text[i : i + chunk_size] for i in range(0, len(text), step)]
            return [s for s in splits if s.strip()]

        parts = text.split(sep)
        if len(parts) <= 1:
            continue

        # Merge small parts into chunks
        chunks = []
        current = ""

        for part in parts:
            test = current + sep + part if current else part

            if len(test) <= chunk_size:
                current = test
            else:
                if current:
                    chunks.append(current.strip())
                # If a single part exceeds chunk_size, recursively split it
                if len(part) > chunk_size:
                    remaining_seps = separators[separators.index(sep) + 1 :]
                    sub_chunks = recursive_character_split(
                        part, chunk_size, chunk_overlap, remaining_seps
                    )
                    chunks.extend(sub_chunks)
                    current = ""
                else:
                    current = part

        if current.strip():
            chunks.append(current.strip())

        if chunks:
            # Add overlap between chunks
            if chunk_overlap > 0 and len(chunks) > 1:
                overlapped = [chunks[0]]
                for i in range(1, len(chunks)):
                    prev = chunks[i - 1]
                    overlap_text = prev[-chunk_overlap:] if len(prev) > chunk_overlap else prev
                    # Find a clean break point in the overlap
                    break_point = overlap_text.rfind(" ")
                    if break_point > 0:
                        overlap_text = overlap_text[break_point + 1 :]
                    overlapped.append(overlap_text + " " + chunks[i])
                return [c for c in overlapped if c.strip()]

            return [c for c in chunks if c.strip()]

    return [text] if text.strip() else []


def chunk_document(
    content: str,
    base_metadata: dict[str, str],
    sections: list[dict[str, str]] | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[TextChunk]:
    """Chunk a document into indexed text chunks with metadata.

    If sections are provided (from header-aware parsing), chunks
    within each section to preserve document structure.

    Args:
        content: Full document text.
        base_metadata: Metadata to attach to every chunk.
        sections: Optional list of {content, section} dicts.
        chunk_size: Max characters per chunk.
        chunk_overlap: Overlap between chunks.

    Returns:
        List of TextChunk objects with sequential chunk_index.
    """
    chunks: list[TextChunk] = []
    chunk_index = 0

    if sections:
        # Chunk each section independently to preserve structure
        for section in sections:
            section_text = section["content"]
            section_name = section.get("section", "Unknown")

            text_chunks = recursive_character_split(section_text, chunk_size, chunk_overlap)

            for text in text_chunks:
                meta = {**base_metadata, "section": section_name}
                if "page" in section:
                    meta["page"] = section["page"]
                if "level" in section:
                    meta["heading_level"] = section["level"]

                chunks.append(
                    TextChunk(
                        content=text,
                        chunk_index=chunk_index,
                        metadata=meta,
                    )
                )
                chunk_index += 1
    else:
        # Chunk the entire document
        text_chunks = recursive_character_split(content, chunk_size, chunk_overlap)
        for text in text_chunks:
            chunks.append(
                TextChunk(
                    content=text,
                    chunk_index=chunk_index,
                    metadata=base_metadata,
                )
            )
            chunk_index += 1

    return chunks
