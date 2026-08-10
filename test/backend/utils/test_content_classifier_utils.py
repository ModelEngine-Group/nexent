"""Tests for content_classifier_utils."""

import pytest

from utils.content_classifier_utils import ContentClassifier


class TestContentClassifier:
    """Test cases for ContentClassifier."""

    def test_basic_classification(self):
        """Test basic content classification."""
        classifier = ContentClassifier()

        results = classifier.classify("<SKILL>\n")
        assert len(results) == 0
        assert classifier.state == "skill_body"

    def test_skill_body_content(self):
        """Test skill body content classification."""
        classifier = ContentClassifier()

        classifier.classify("<SKILL>\n")
        results = classifier.classify("some skill content")

        assert len(results) == 1
        assert results[0]["type"] == "skill_body"
        assert results[0]["content"] == "some skill content"

    def test_summary_tag(self):
        """Test <SUMMARY> tag matching."""
        classifier = ContentClassifier()

        classifier.classify("<SUMMARY>\n")
        assert classifier.state == "summary"

        results = classifier.classify("summary text here")
        assert len(results) >= 1
        assert results[0]["type"] == "summary"
        assert "summary text here" in results[0]["content"]

    def test_summary_with_content_chunk(self):
        """Test <SUMMARY>content</SUMMARY> in single chunk."""
        classifier = ContentClassifier()

        # Simulate receiving full content in one chunk
        results = classifier.classify("<SUMMARY>\nmy summary\n</SUMMARY>\n")

        # Should have at least the summary content event
        summary_events = [r for r in results if r.get("type") == "summary"]
        assert len(summary_events) >= 1
        assert "my summary" in summary_events[0]["content"]

    def test_summary_close_tag_split_after_text(self):
        """Test split </SUMMARY> tag after normal text is parsed as a tag."""
        classifier = ContentClassifier()

        classifier.classify("<SUMMARY>\n")
        results = []
        results.extend(classifier.classify("summary...\n</"))
        results.extend(classifier.classify("SUMMARY"))
        results.extend(classifier.classify(">\n"))
        results.extend(classifier.classify("ignored"))

        summary_text = "".join(r["content"] for r in results if r.get("type") == "summary")
        others_text = "".join(r["content"] for r in results if r.get("type") == "others")
        assert summary_text == "summary...\n"
        assert others_text == "ignored"
        assert classifier.state == "others"

    def test_process_non_tag_content_waits_on_leading_tag_start(self):
        """Test non-tag processing keeps a leading tag start in the buffer."""
        classifier = ContentClassifier()
        classifier.buffer = "<"

        results = classifier._process_non_tag_content()

        assert results == []
        assert classifier.buffer == "<"

    def test_full_skill_flow(self):
        """Test full SKILL -> body -> </SKILL> -> summary flow."""
        classifier = ContentClassifier()

        # Start SKILL
        classifier.classify("<SKILL>\n")
        assert classifier.state == "skill_body"

        # Add skill body content
        results = classifier.classify("# Skill Title")
        assert len(results) >= 1
        assert results[0]["type"] == "skill_body"

        # End SKILL
        classifier.classify("\n</SKILL>\n")
        assert classifier.state == "summary"

        # Add summary content
        results = classifier.classify("This is a summary")
        summary_events = [r for r in results if r.get("type") == "summary"]
        assert len(summary_events) >= 1
        assert "This is a summary" in summary_events[0]["content"]

    def test_file_tag(self):
        """Test <FILE path="..."> tag matching."""
        classifier = ContentClassifier()

        classifier.classify('<FILE path="test.py">\n')
        assert classifier.state == "file"

        results = classifier.classify("file content")
        assert len(results) >= 1
        assert results[0]["type"] == "file_content"
        assert "file content" in results[0]["content"]

    def test_file_placeholder_path_is_not_file_content(self):
        """Test placeholder file paths are not treated as generated files."""
        classifier = ContentClassifier()

        results = []
        results.extend(classifier.classify('Use <FILE path="...">'))
        results.extend(classifier.classify("wrapped content"))
        results.extend(classifier.classify("</FILE>"))
        results.extend(classifier.classify(" after"))

        assert not any(r.get("type") == "file_content" for r in results)
        assert classifier.state == "others"

    def test_file_path_rejects_parent_traversal(self):
        """Test parent traversal paths are not treated as generated files."""
        classifier = ContentClassifier()
        classifier.classify("<SKILL>\n")

        results = []
        results.extend(classifier.classify('<FILE path="../secret.md">'))
        results.extend(classifier.classify("hidden"))
        results.extend(classifier.classify("</FILE>"))
        results.extend(classifier.classify(" body"))

        assert not any(r.get("type") == "file_content" for r in results)
        assert classifier.state == "skill_body"

    def test_file_path_allows_nested_relative_path(self):
        """Test nested relative file paths are treated as generated files."""
        classifier = ContentClassifier()

        results = classifier.classify('<FILE path="references/zodiac_data.md">\n')

        assert classifier.state == "file"
        assert results == [
            {
                "type": "file_content",
                "content": "",
                "path": "references/zodiac_data.md",
                "is_new_file": True,
            }
        ]

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "/absolute/path.md",
            r"references\windows.md",
            "references//empty.md",
            "./relative.md",
        ],
    )
    def test_file_path_rejects_unsafe_paths(self, path):
        """Test unsafe file paths are not treated as generated files."""
        classifier = ContentClassifier()

        results = classifier.classify(f'<FILE path="{path}">')
        results.extend(classifier.classify("content"))

        assert not any(r.get("type") == "file_content" for r in results)
        assert classifier.state == "others"

    def test_file_path_rejects_blank_after_strip(self):
        """Test blank file paths are rejected after trimming whitespace."""
        classifier = ContentClassifier()

        assert classifier._is_valid_file_path(" ") is False

    def test_end_file_tag_outside_file_state_does_not_change_state(self):
        """Test </FILE> outside file state does not leave the current state."""
        classifier = ContentClassifier()
        classifier.classify("<SKILL>\n")

        classifier.classify("</FILE>\n")

        assert classifier.state == "skill_body"
        assert classifier.current_file_path is None

    def test_create_event_ignores_empty_content(self):
        """Test empty content does not create a stream event."""
        classifier = ContentClassifier()

        assert classifier._create_event("") == {}

    def test_others_content(self):
        """Test content outside tags is classified as 'others'."""
        classifier = ContentClassifier()

        results = classifier.classify("thinking content")
        assert len(results) >= 1
        assert results[0]["type"] == "others"

    def test_streaming_characters(self):
        """Test streaming character-by-character classification."""
        classifier = ContentClassifier()

        classifier.classify("<SKILL>\n")
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
        results = classifier.classify(">\n")

        assert classifier.state == "skill_body"
        assert len(results) == 0  # Tag itself produces no content event

    def test_dos_protection_tag_count(self):
        """Test DoS protection limits tag count."""
        classifier = ContentClassifier()

        # Set max tag count to 3 for testing
        classifier.MAX_TAG_COUNT = 3

        classifier.classify("<SKILL>\n")
        assert classifier.tag_count == 1
        classifier.classify("</SKILL>\n")
        assert classifier.tag_count == 2
        classifier.classify("<SKILL>\n")
        assert classifier.tag_count == 3

        # 4th tag should be blocked
        results = classifier.classify("</SKILL>\n")
        assert classifier.tag_count == 3
        # Content after 4th tag should not be processed
        assert len(results) == 0

    def test_reset_state_after_summary_end(self):
        """Test state resets to 'others' after </SUMMARY>."""
        classifier = ContentClassifier()

        classifier.classify("<SUMMARY>\n")
        assert classifier.state == "summary"

        classifier.classify("\n</SUMMARY>\n")
        assert classifier.state == "others"

        results = classifier.classify("final content")
        assert len(results) >= 1
        assert results[0]["type"] == "others"

    def test_complex_nested_flow(self):
        """Test complex flow with multiple tag transitions."""
        classifier = ContentClassifier()

        # Start skill
        classifier.classify("<SKILL>\n")
        assert classifier.state == "skill_body"

        # Add body content
        results = classifier.classify("body content")
        assert results[0]["type"] == "skill_body"

        # Start file
        classifier.classify('\n<FILE path="test.py">\n')
        assert classifier.state == "file"

        # Add file content
        results = classifier.classify("file data")
        assert results[0]["type"] == "file_content"

        # End file
        classifier.classify("\n</FILE>\n")
        assert classifier.state == "skill_body"

        # More body content
        results = classifier.classify("more body")
        assert results[0]["type"] == "skill_body"

        # End skill
        classifier.classify("\n</SKILL>\n")
        assert classifier.state == "summary"

        # Summary content
        results = classifier.classify("final summary")
        assert results[0]["type"] == "summary"

    def test_preserves_origin_type_outside_control_blocks(self):
        classifier = ContentClassifier()

        results = classifier.classify(
            "I need one clarification.",
            origin_type="model_output_thinking",
        )

        assert results == [
            {
                "type": "model_output_thinking",
                "content": "I need one clarification.",
                "origin_type": "model_output_thinking",
            }
        ]

    def test_inline_backticked_control_tags_remain_raw_model_output(self):
        classifier = ContentClassifier()

        results = []
        for chunk in ["存量技能内容实际上是空的（`", "<SKILL>", "` 和 `", "</SKILL>", "` 之间没有内容）。"]:
            results.extend(
                classifier.classify(
                    chunk,
                    origin_type="model_output_deep_thinking",
                )
            )
        results.extend(classifier.flush())

        assert not any(event["type"] in {"skill_body", "summary"} for event in results)
        assert "".join(event["content"] for event in results) == (
            "存量技能内容实际上是空的（`<SKILL>` 和 `</SKILL>` 之间没有内容）。"
        )
        assert classifier.saw_control_tag is False

    def test_standalone_control_tags_split_across_chunks_are_parsed(self):
        classifier = ContentClassifier()

        results = []
        for chunk in ["<SK", "ILL>", "\n---\nname: demo\n---\n", "</SKILL>", "\n"]:
            results.extend(classifier.classify(chunk, origin_type="model_output_code"))

        assert "".join(event["content"] for event in results if event["type"] == "skill_body") == (
            "---\nname: demo\n---\n"
        )
        assert classifier.saw_control_tag is True

    def test_skill_tag_after_reasoning_without_leading_newline_is_parsed(self):
        classifier = ContentClassifier()

        results = []
        results.extend(
            classifier.classify(
                "Reasoning finished.",
                origin_type="model_output_deep_thinking",
            )
        )
        results.extend(
            classifier.classify("<", origin_type="model_output_thinking")
        )
        results.extend(
            classifier.classify(
                "SKILL>\n---\nname: demo\n---\n",
                origin_type="model_output_thinking",
            )
        )

        assert results[0]["type"] == "model_output_deep_thinking"
        assert "".join(
            event["content"] for event in results if event["type"] == "skill_body"
        ) == "---\nname: demo\n---\n"
        assert not any(
            event["type"] == "model_output_thinking"
            and "SKILL" in event["content"]
            for event in results
        )
        assert classifier.state == "skill_body"

    def test_semantic_events_carry_origin_type(self):
        classifier = ContentClassifier()

        results = classifier.classify(
            "<SKILL>\nbody\n</SKILL>\n",
            origin_type="model_output_code",
        )

        assert results == [
            {
                "type": "skill_body",
                "content": "body\n",
                "path": "SKILL.md",
                "origin_type": "model_output_code",
            }
        ]

    def test_flush_emits_incomplete_tag_tail(self):
        classifier = ContentClassifier()
        assert classifier.classify("partial <", origin_type="model_output_thinking")

        results = classifier.flush()

        assert results == [
            {
                "type": "model_output_thinking",
                "content": "<",
                "origin_type": "model_output_thinking",
            }
        ]

    def test_unknown_tag_is_emitted_as_raw_content(self):
        classifier = ContentClassifier()
        results = classifier.classify("before <UNKNOWN> after")
        assert "<UNKNOWN>" in "".join(event["content"] for event in results)
        assert all(event["type"] == "others" for event in results)

    def test_overlong_tag_uses_dos_protection(self):
        classifier = ContentClassifier()
        classifier.MAX_TAG_LENGTH = 5
        results = classifier.classify("<123456789>content")
        assert results[0]["content"] == "<"
        assert classifier.buffer != "<123456789>content"

    def test_buffer_overflow_emits_oldest_content(self):
        classifier = ContentClassifier()
        classifier.MAX_BUFFER_SIZE = 5
        results = classifier.classify("abcdefgh", origin_type="model_output")
        assert results == [
            {
                "type": "model_output",
                "content": "abc",
                "origin_type": "model_output",
            },
            {
                "type": "model_output",
                "content": "defgh",
                "origin_type": "model_output",
            },
        ]
        assert classifier.buffer == ""

    def test_file_close_restores_previous_summary_state(self):
        classifier = ContentClassifier()
        classifier.classify("<SUMMARY>\n")
        classifier.classify('<FILE path="notes.txt">\n')
        classifier.classify("note\n")
        classifier.classify("</FILE>\n")
        assert classifier.state == "summary"
        assert classifier.classify("done")[-1]["type"] == "summary"
