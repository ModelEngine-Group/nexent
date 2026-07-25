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

    def test_unknown_tag_followed_by_skill(self):
        """Unknown reasoning tag (<think>) must not swallow the following <SKILL>.

        Reproduces the regression where <think>xxx</think><SKILL>body</SKILL> was
        emitted entirely as 'others' because the buffer of non-tag content was
        flushed past the embedded '<SKILL>' tag.
        """
        classifier = ContentClassifier()

        results = classifier.classify("<think>reasoning</think><SKILL>body</SKILL>")

        skill_events = [r for r in results if r.get("type") == "skill_body"]
        assert len(skill_events) >= 1, (
            "Expected at least one skill_body event; got: " + repr(results)
        )
        combined = "".join(e["content"] for e in skill_events)
        assert "body" in combined

        # Reasoning content should still surface as 'others'
        others_events = [r for r in results if r.get("type") == "others"]
        assert any("reasoning" in e["content"] for e in others_events), (
            "Expected the reasoning text to be preserved as 'others'; got: " + repr(results)
        )

        # After </SKILL> the state should be 'summary'
        assert classifier.state == "summary"

    def test_text_with_embedded_skill_tag(self):
        """A known tag embedded in non-tag text must still be recognised."""
        classifier = ContentClassifier()

        results = classifier.classify("hello world<SKILL>body</SKILL>")

        skill_events = [r for r in results if r.get("type") == "skill_body"]
        assert len(skill_events) >= 1
        assert any("body" in e["content"] for e in skill_events)
        # Prefix text is still surfaced as 'others'
        others_events = [r for r in results if r.get("type") == "others"]
        assert any("hello world" in e["content"] for e in others_events)

    def test_streaming_unknown_then_skill(self):
        """Streaming chunks where <think> and <SKILL> arrive separately still classify correctly."""
        classifier = ContentClassifier()

        # Reasoning tag arrives first, then SKILL body in a separate chunk
        classifier.classify("<think>reasoning")
        classifier.classify("</think><SKILL>body")
        results = classifier.classify(" content</SKILL>")

        skill_events = [r for r in results if r.get("type") == "skill_body"]
        assert any("body" in e["content"] or "content" in e["content"]
                   for e in skill_events)

    def test_unknown_tag_emitted_as_single_event(self):
        """An unknown tag should be emitted as a single chunk, not split char-by-char."""
        classifier = ContentClassifier()

        results = classifier.classify("<think>reasoning</think> rest")

        # No split on '<' so the '<think>' should appear in a single others event
        others_events = [r for r in results if r.get("type") == "others"]
        assert any("<think>" in e["content"] for e in others_events), (
            "Expected <think> to be preserved in a single others event; got: "
            + repr(results)
        )

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
