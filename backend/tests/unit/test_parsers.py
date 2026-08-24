"""Unit tests for document parsers."""

from __future__ import annotations

import pytest

from app.ingestion.parsers.html_parser import HTMLParser
from app.ingestion.parsers.markdown_parser import MarkdownParser
from app.ingestion.parsers.text_parser import TextParser


class TestMarkdownParser:
    """Tests for the Markdown parser."""

    def test_parse_simple_markdown(self, tmp_path):
        """Should extract content and detect title from H1."""
        md_content = "# My Document\n\nThis is the introduction.\n\n## Section 1\n\nContent of section 1.\n\n## Section 2\n\nContent of section 2."  # noqa: E501
        file_path = tmp_path / "test.md"
        file_path.write_text(md_content)

        parser = MarkdownParser()
        result = parser.parse(file_path)

        assert not result.is_empty
        assert "My Document" in result.metadata.get("title", "")
        assert len(result.sections) >= 2

    def test_parse_empty_markdown(self, tmp_path):
        """Should handle empty files."""
        file_path = tmp_path / "empty.md"
        file_path.write_text("")

        parser = MarkdownParser()
        result = parser.parse(file_path)
        assert result.is_empty

    def test_parse_bytes(self):
        """Should parse from raw bytes."""
        content = b"# Title\n\nSome content here."
        parser = MarkdownParser()
        result = parser.parse_bytes(content, "test.md")

        assert "Title" in result.metadata.get("title", "")
        assert "Some content here" in result.content

    def test_parse_nonexistent_file(self):
        """Should raise FileNotFoundError for missing files."""
        parser = MarkdownParser()
        with pytest.raises(FileNotFoundError):
            parser.parse("/nonexistent/path.md")

    def test_section_splitting(self, tmp_path):
        """Should split content by headers."""
        content = "# Main\n\nIntro\n\n## Part A\n\nA content\n\n## Part B\n\nB content"
        file_path = tmp_path / "test.md"
        file_path.write_text(content)

        parser = MarkdownParser()
        result = parser.parse(file_path)

        section_names = [s.get("section", "") for s in result.sections]
        assert "Part A" in section_names or "Main" in section_names

    def test_content_hash_deterministic(self, tmp_path):
        """Same content should produce same hash."""
        content = "# Test\n\nSame content"
        file_path = tmp_path / "test.md"
        file_path.write_text(content)

        parser = MarkdownParser()
        result1 = parser.parse(file_path)
        result2 = parser.parse(file_path)

        assert result1.content_hash == result2.content_hash


class TestTextParser:
    """Tests for the plain text parser."""

    def test_parse_simple_text(self, tmp_path):
        """Should extract paragraphs as sections."""
        content = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        file_path = tmp_path / "test.txt"
        file_path.write_text(content)

        parser = TextParser()
        result = parser.parse(file_path)

        assert not result.is_empty
        assert len(result.sections) == 3

    def test_parse_empty_text(self, tmp_path):
        """Should handle empty files."""
        file_path = tmp_path / "empty.txt"
        file_path.write_text("   \n   \n   ")

        parser = TextParser()
        result = parser.parse(file_path)
        # After cleaning, content may be empty or very minimal
        assert isinstance(result.content, str)


class TestHTMLParser:
    """Tests for the HTML parser."""

    def test_parse_simple_html(self, tmp_path):
        """Should extract text and strip tags."""
        html = "<html><head><title>Test Page</title></head><body><h1>Heading</h1><p>Content here.</p></body></html>"  # noqa: E501
        file_path = tmp_path / "test.html"
        file_path.write_text(html)

        parser = HTMLParser()
        result = parser.parse(file_path)

        assert "Heading" in result.content
        assert "Content here" in result.content
        assert "<html>" not in result.content

    def test_removes_script_tags(self, tmp_path):
        """Should remove script and style content."""
        html = "<html><body><script>alert('xss')</script><p>Real content</p><style>.x{color:red}</style></body></html>"  # noqa: E501
        file_path = tmp_path / "test.html"
        file_path.write_text(html)

        parser = HTMLParser()
        result = parser.parse(file_path)

        assert "alert" not in result.content
        assert "color:red" not in result.content
        assert "Real content" in result.content

    def test_extracts_title(self):
        """Should extract page title from meta."""
        html = "<html><head><title>My Page Title</title></head><body><p>Content</p></body></html>"
        parser = HTMLParser()
        result = parser.parse_bytes(html.encode(), "test.html")

        assert result.metadata.get("title") == "My Page Title"
