"""Tests for content_classifier_utils."""

import pytest

from utils.content_classifier_utils import ContentClassifier


class TestContentClassifier:
    """Test cases for ContentClassifier."""

    def test_basic_classification(self):
        """Test basic content classification."""
        classifier = ContentClassifier()

        results = classifier.classify("<SKILL>")
        assert len(results) == 0
        assert classifier.state == "skill_body"

    def test_skill_body_content(self):
        """Test skill body content classification."""
        classifier = ContentClassifier()

        classifier.classify("<SKILL>")
        results = classifier.classify("some skill content")

        assert len(results) == 1
        assert results[0]["type"] == "skill_body"
        assert results[0]["content"] == "some skill content"

    def test_summary_tag(self):
        """Test <SUMMARY> tag matching."""
        classifier = ContentClassifier()

        classifier.classify("<SUMMARY>")
        assert classifier.state == "summary"

        results = classifier.classify("summary text here")
        assert len(results) >= 1
        assert results[0]["type"] == "summary"
        assert "summary text here" in results[0]["content"]

    def test_summary_with_content_chunk(self):
        """Test <SUMMARY>content</SUMMARY> in single chunk."""
        classifier = ContentClassifier()

        # Simulate receiving full content in one chunk
        results = classifier.classify("<SUMMARY>my summary</SUMMARY>")

        # Should have at least the summary content event
        summary_events = [r for r in results if r.get("type") == "summary"]
        assert len(summary_events) >= 1
        assert "my summary" in summary_events[0]["content"]

    def test_full_skill_flow(self):
        """Test full SKILL -> body -> </SKILL> -> summary flow."""
        classifier = ContentClassifier()

        # Start SKILL
        classifier.classify("<SKILL>")
        assert classifier.state == "skill_body"

        # Add skill body content
        results = classifier.classify("# Skill Title")
        assert len(results) >= 1
        assert results[0]["type"] == "skill_body"

        # End SKILL
        classifier.classify("</SKILL>")
        assert classifier.state == "summary"

        # Add summary content
        results = classifier.classify("This is a summary")
        summary_events = [r for r in results if r.get("type") == "summary"]
        assert len(summary_events) >= 1
        assert "This is a summary" in summary_events[0]["content"]

    def test_file_tag(self):
        """Test <FILE path="..."> tag matching."""
        classifier = ContentClassifier()

        classifier.classify('<FILE path="test.py">')
        assert classifier.state == "file"

        results = classifier.classify("file content")
        assert len(results) >= 1
        assert results[0]["type"] == "file_content"
        assert "file content" in results[0]["content"]

    def test_others_content(self):
        """Test content outside tags is classified as 'others'."""
        classifier = ContentClassifier()

        results = classifier.classify("thinking content")
        assert len(results) >= 1
        assert results[0]["type"] == "others"

    def test_streaming_characters(self):
        """Test streaming character-by-character classification."""
        classifier = ContentClassifier()

        classifier.classify("<SKILL>")
        results = classifier.classify("a")

        assert len(results) == 1
        assert results[0]["type"] == "skill_body"
        assert results[0]["content"] == "a"

    def test_multiple_tags_streaming(self):
        """Test multiple tags received in streaming chunks."""
        classifier = ContentClassifier()

        # Stream character by character
        classifier.classify("<")
        classifier.classify("S")
        classifier.classify("KILL")
        results = classifier.classify(">")

        assert classifier.state == "skill_body"
        assert len(results) == 0  # Tag itself produces no content event

    def test_dos_protection_tag_count(self):
        """Test DoS protection limits tag count."""
        classifier = ContentClassifier()

        # Set max tag count to 3 for testing
        classifier.MAX_TAG_COUNT = 3

        classifier.classify("<SKILL>")
        assert classifier.tag_count == 1
        classifier.classify("</SKILL>")
        assert classifier.tag_count == 2
        classifier.classify("<SKILL>")
        assert classifier.tag_count == 3

        # 4th tag should be blocked
        results = classifier.classify("</SKILL>")
        assert classifier.tag_count == 3
        # Content after 4th tag should not be processed
        assert len(results) == 0

    def test_reset_state_after_summary_end(self):
        """Test state resets to 'others' after </SUMMARY>."""
        classifier = ContentClassifier()

        classifier.classify("<SUMMARY>")
        assert classifier.state == "summary"

        classifier.classify("</SUMMARY>")
        assert classifier.state == "others"

        results = classifier.classify("final content")
        assert len(results) >= 1
        assert results[0]["type"] == "others"

    def test_complex_nested_flow(self):
        """Test complex flow with multiple tag transitions."""
        classifier = ContentClassifier()

        # Start skill
        classifier.classify("<SKILL>")
        assert classifier.state == "skill_body"

        # Add body content
        results = classifier.classify("body content")
        assert results[0]["type"] == "skill_body"

        # Start file
        classifier.classify('<FILE path="test.py">')
        assert classifier.state == "file"

        # Add file content
        results = classifier.classify("file data")
        assert results[0]["type"] == "file_content"

        # End file
        classifier.classify("</FILE>")
        assert classifier.state == "skill_body"

        # More body content
        results = classifier.classify("more body")
        assert results[0]["type"] == "skill_body"

        # End skill
        classifier.classify("</SKILL>")
        assert classifier.state == "summary"

        # Summary content
        results = classifier.classify("final summary")
        assert results[0]["type"] == "summary"
