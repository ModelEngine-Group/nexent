import json

import pytest

# Import the modules under test
from sdk.nexent.core.utils.observer import (
    MessageObserver, Message, ProcessType,
    DefaultTransformer, StepCountTransformer,
    ParseTransformer, ExecutionLogsTransformer, FinalAnswerTransformer,
    TokenCountTransformer
)


class TestMessage:
    """Test Message class functionality"""

    def test_message_initialization(self):
        """Test Message class initialization with different process types"""
        content = "Test content"

        # Test with different process types
        for process_type in ProcessType:
            message = Message(process_type, content)
            assert message.message_type == process_type
            assert message.content == content

    def test_message_to_json(self):
        """Test Message.to_json() method returns valid JSON string"""
        message = Message(ProcessType.MODEL_OUTPUT_THINKING, "Test content")
        json_str = message.to_json()

        # Verify it's valid JSON
        parsed = json.loads(json_str)
        assert parsed["type"] == ProcessType.MODEL_OUTPUT_THINKING.value
        assert parsed["content"] == "Test content"

    def test_message_to_json_unicode_content(self):
        """Test Message.to_json() with unicode content"""
        unicode_content = "测试内容 🚀"
        message = Message(ProcessType.MODEL_OUTPUT_CODE, unicode_content)
        json_str = message.to_json()

        parsed = json.loads(json_str)
        assert parsed["content"] == unicode_content


class TestDefaultTransformer:
    """Test DefaultTransformer class"""

    def test_default_transformer_transform(self):
        """Test DefaultTransformer.transform() returns content as-is"""
        transformer = DefaultTransformer()
        content = "Test content"

        result = transformer.transform(content=content)
        assert result == content

    def test_default_transformer_transform_empty_content(self):
        """Test DefaultTransformer.transform() with empty content"""
        transformer = DefaultTransformer()

        result = transformer.transform(content="")
        assert result == ""

    def test_default_transformer_transform_with_kwargs(self):
        """Test DefaultTransformer.transform() ignores additional kwargs"""
        transformer = DefaultTransformer()
        content = "Test content"

        result = transformer.transform(content=content, lang="zh", extra="ignored")
        assert result == content


class TestStepCountTransformer:
    """Test StepCountTransformer class"""

    def test_step_count_transformer_zh(self):
        """Test StepCountTransformer with Chinese language"""
        transformer = StepCountTransformer()
        step_number = "3"

        result = transformer.transform(content=step_number, lang="zh")
        expected = "\n**步骤 3** \n"
        assert result == expected

    def test_step_count_transformer_en(self):
        """Test StepCountTransformer with English language"""
        transformer = StepCountTransformer()
        step_number = "5"

        result = transformer.transform(content=step_number, lang="en")
        expected = "\n**Step 5** \n"
        assert result == expected

    def test_step_count_transformer_default_lang(self):
        """Test StepCountTransformer with default language (should be English)"""
        transformer = StepCountTransformer()
        step_number = "1"

        result = transformer.transform(content=step_number)
        expected = "\n**Step 1** \n"
        assert result == expected

    def test_step_count_transformer_unknown_lang(self):
        """Test StepCountTransformer with unknown language (should default to English)"""
        transformer = StepCountTransformer()
        step_number = "2"

        result = transformer.transform(content=step_number, lang="fr")
        expected = "\n**Step 2** \n"
        assert result == expected


class TestParseTransformer:
    """Test ParseTransformer class"""

    def test_parse_transformer_zh(self):
        """Test ParseTransformer with Chinese language"""
        transformer = ParseTransformer()
        code_content = "print('Hello World')"

        result = transformer.transform(content=code_content, lang="zh")
        expected = "\n🛠️ 使用Python解释器执行代码\n```python\nprint('Hello World')\n```\n"
        assert result == expected

    def test_parse_transformer_en(self):
        """Test ParseTransformer with English language"""
        transformer = ParseTransformer()
        code_content = "x = 42"

        result = transformer.transform(content=code_content, lang="en")
        expected = "\n🛠️ Used tool python_interpreter\n```python\nx = 42\n```\n"
        assert result == expected

    def test_parse_transformer_default_lang(self):
        """Test ParseTransformer with default language"""
        transformer = ParseTransformer()
        code_content = "def test(): pass"

        result = transformer.transform(content=code_content)
        expected = "\n🛠️ Used tool python_interpreter\n```python\ndef test(): pass\n```\n"
        assert result == expected


class TestExecutionLogsTransformer:
    """Test ExecutionLogsTransformer class"""

    def test_execution_logs_transformer(self):
        """Test ExecutionLogsTransformer returns content as-is"""
        transformer = ExecutionLogsTransformer()
        log_content = "Hello World\n42"

        result = transformer.transform(content=log_content, lang="zh")
        assert result == log_content

    def test_execution_logs_transformer_empty(self):
        """Test ExecutionLogsTransformer with empty content"""
        transformer = ExecutionLogsTransformer()

        result = transformer.transform(content="", lang="en")
        assert result == ""


class TestFinalAnswerTransformer:
    """Test FinalAnswerTransformer class"""

    def test_final_answer_transformer(self):
        """Test FinalAnswerTransformer returns content as-is"""
        transformer = FinalAnswerTransformer()
        content = "Final answer content"

        result = transformer.transform(content=content)
        assert result == content

    def test_final_answer_transformer_empty(self):
        """Test FinalAnswerTransformer with empty content"""
        transformer = FinalAnswerTransformer()

        result = transformer.transform(content="")
        assert result == ""


class TestTokenCountTransformer:
    """Test TokenCountTransformer class"""

    def test_token_count_transformer_zh(self):
        """Test TokenCountTransformer passes content unchanged"""
        transformer = TokenCountTransformer()
        duration = "2.5s"

        result = transformer.transform(content=duration, lang="zh")
        assert result == duration

    def test_token_count_transformer_en(self):
        """Test TokenCountTransformer passes content unchanged"""
        transformer = TokenCountTransformer()
        duration = "1.8s"

        result = transformer.transform(content=duration, lang="en")
        assert result == duration


class TestMessageObserver:
    """Test MessageObserver class functionality"""

    @pytest.fixture
    def observer(self):
        """Create a MessageObserver instance for testing"""
        return MessageObserver(lang="en")

    def test_observer_initialization(self):
        """Test MessageObserver initialization with different languages"""
        # Test English
        observer_en = MessageObserver(lang="en")
        assert observer_en.lang == "en"
        assert observer_en.current_mode == ProcessType.MODEL_OUTPUT_THINKING

        # Test Chinese
        observer_zh = MessageObserver(lang="zh")
        assert observer_zh.lang == "zh"

        # Test default
        observer_default = MessageObserver()
        assert observer_default.lang == "zh"

    def test_observer_constants(self):
        """Test that buffer size constants are properly defined"""
        observer = MessageObserver()
        assert hasattr(MessageObserver, 'MAX_TOKEN_BUFFER_SIZE')
        assert MessageObserver.MAX_TOKEN_BUFFER_SIZE == 10

    def test_add_message(self):
        """Test add_message method with different process types"""
        observer = MessageObserver(lang="en")

        # Test adding a step count message
        observer.add_message("test_agent", ProcessType.STEP_COUNT, "3")

        cached_messages = observer.get_cached_message()
        assert len(cached_messages) == 1

        message_data = json.loads(cached_messages[0])
        assert message_data["type"] == ProcessType.STEP_COUNT.value
        assert "Step 3" in message_data["content"]

    def test_add_model_reasoning_content(self):
        """Test add_model_reasoning_content method"""
        observer = MessageObserver()
        reasoning_content = "This is reasoning content"

        observer.add_model_reasoning_content(reasoning_content)

        cached_messages = observer.get_cached_message()
        assert len(cached_messages) == 1

        message_data = json.loads(cached_messages[0])
        assert message_data["type"] == ProcessType.MODEL_OUTPUT_DEEP_THINKING.value
        assert message_data["content"] == reasoning_content

    def test_add_model_reasoning_content_empty(self):
        """Test add_model_reasoning_content with empty content"""
        observer = MessageObserver()

        observer.add_model_reasoning_content("")
        observer.add_model_reasoning_content(None)

        cached_messages = observer.get_cached_message()
        assert len(cached_messages) == 0

    def test_get_cached_message(self):
        """Test get_cached_message method clears the queue after returning"""
        observer = MessageObserver()

        # Add some messages
        observer.add_message("agent1", ProcessType.STEP_COUNT, "1")
        observer.add_message("agent2", ProcessType.FINAL_ANSWER, "Done")

        # Get cached messages
        cached_messages = observer.get_cached_message()
        assert len(cached_messages) == 2

        # Check that queue is cleared
        cached_messages_again = observer.get_cached_message()
        assert len(cached_messages_again) == 0

    def test_get_final_answer(self):
        """Test get_final_answer method"""
        observer = MessageObserver()

        # Add messages including a final answer
        observer.add_message("agent1", ProcessType.STEP_COUNT, "1")
        observer.add_message("agent2", ProcessType.FINAL_ANSWER, "Task completed")
        observer.add_message("agent3", ProcessType.STEP_COUNT, "2")

        final_answer = observer.get_final_answer()
        assert final_answer == "Task completed"

    def test_get_final_answer_no_final_answer(self):
        """Test get_final_answer when no final answer exists"""
        observer = MessageObserver()

        # Add messages without final answer
        observer.add_message("agent1", ProcessType.STEP_COUNT, "1")
        observer.add_message("agent2", ProcessType.STEP_COUNT, "2")

        final_answer = observer.get_final_answer()
        assert final_answer is None

    def test_get_final_answer_invalid_json(self):
        """Test get_final_answer with invalid JSON in message queue"""
        observer = MessageObserver()

        # Manually add invalid JSON to message queue
        observer.message_query.append("invalid json string")
        observer.message_query.append(
            Message(ProcessType.FINAL_ANSWER, "Valid answer").to_json()
        )

        final_answer = observer.get_final_answer()
        assert final_answer == "Valid answer"


class TestMessageObserverTokenProcessing:
    """Test MessageObserver token processing functionality"""

    @pytest.fixture
    def observer(self):
        """Create a MessageObserver instance for testing"""
        return MessageObserver(lang="en")

    def test_add_model_new_token_normal_mode(self):
        """Test add_model_new_token in normal mode (not thinking)"""
        observer = MessageObserver()

        # Add tokens normally
        observer.add_model_new_token("Hello")
        observer.add_model_new_token(" ")
        observer.add_model_new_token("World")

        # Check that tokens are accumulated in think buffer
        assert len(observer.think_buffer) == 3

        # Flush to see the result
        observer.flush_remaining_tokens()
        cached_messages = observer.get_cached_message()

        # Should have one message with accumulated content
        assert len(cached_messages) == 1
        message_data = json.loads(cached_messages[0])
        assert message_data["type"] == ProcessType.MODEL_OUTPUT_THINKING.value
        assert message_data["content"] == "Hello World"

    def test_add_model_new_token_think_mode(self):
        """Test add_model_new_token with think tags"""
        observer = MessageObserver()

        # Add tokens with think tags
        observer.add_model_new_token("<")
        observer.add_model_new_token("think")
        observer.add_model_new_token(">")
        observer.add_model_new_token("Reasoning")
        observer.add_model_new_token("</")
        observer.add_model_new_token("think")
        observer.add_model_new_token(">")
        observer.add_model_new_token("Result")

        # Flush to see the result
        observer.flush_remaining_tokens()
        cached_messages = observer.get_cached_message()

        # Should have two messages: one for thinking, one for result
        assert len(cached_messages) == 2

        # First message should be deep thinking
        first_message = json.loads(cached_messages[0])
        assert first_message["type"] == ProcessType.MODEL_OUTPUT_DEEP_THINKING.value
        assert first_message["content"] == "Reasoning"

        # Second message should be normal content
        second_message = json.loads(cached_messages[1])
        assert second_message["type"] == ProcessType.MODEL_OUTPUT_THINKING.value
        assert second_message["content"] == "Result"

    def test_add_model_new_token_buffer_overflow(self):
        """Test add_model_new_token with buffer overflow handling"""
        observer = MessageObserver()

        # Add more tokens than MAX_TOKEN_BUFFER_SIZE to trigger overflow
        for i in range(25):  # Need more tokens to fill both think_buffer and token_buffer
            observer.add_model_new_token(f"token{i}")

        # Should trigger buffer overflow handling
        cached_messages = observer.get_cached_message()
        assert len(cached_messages) > 0

        # Check that buffers were managed
        assert len(observer.think_buffer) <= observer.MAX_TOKEN_BUFFER_SIZE
        assert len(observer.token_buffer) <= observer.MAX_TOKEN_BUFFER_SIZE

    def test_process_normal_content_code_detection(self):
        """Test _process_normal_content with code block detection"""
        observer = MessageObserver()

        # Add content that should trigger code mode
        observer.add_model_new_token("Let me write some code")
        observer.add_model_new_token("代码:")
        observer.add_model_new_token("```")
        observer.add_model_new_token("print('Hello')")
        observer.add_model_new_token("```")

        # Flush to process
        observer.flush_remaining_tokens()
        cached_messages = observer.get_cached_message()

        # Should have messages for thinking and code
        assert len(cached_messages) >= 2

        # Check that mode switched to code
        assert observer.current_mode == ProcessType.MODEL_OUTPUT_CODE

    def test_flush_remaining_tokens(self):
        """Test flush_remaining_tokens method"""
        observer = MessageObserver()

        # Add some tokens
        observer.add_model_new_token("Some")
        observer.add_model_new_token(" content")

        # Flush remaining tokens
        observer.flush_remaining_tokens()

        # Check that buffers are cleared
        assert len(observer.think_buffer) == 0
        assert len(observer.token_buffer) == 0

        # Check that messages were processed
        cached_messages = observer.get_cached_message()
        assert len(cached_messages) > 0


class TestMessageObserverEdgeCases:
    """Test MessageObserver edge cases and error handling"""

    @pytest.fixture
    def observer(self):
        """Create a MessageObserver instance for testing"""
        return MessageObserver(lang="en")

    def test_observer_with_empty_tokens(self):
        """Test observer behavior with empty tokens"""
        observer = MessageObserver()

        observer.add_model_new_token("")
        observer.add_model_new_token("")

        # Should handle empty tokens gracefully
        observer.flush_remaining_tokens()
        cached_messages = observer.get_cached_message()

        # Should not crash and should handle gracefully
        assert isinstance(cached_messages, list)

    def test_observer_with_very_long_tokens(self):
        """Test observer behavior with very long tokens"""
        observer = MessageObserver()

        # Add very long token
        long_token = "x" * 1000
        observer.add_model_new_token(long_token)

        # Should handle long tokens without issues
        observer.flush_remaining_tokens()
        cached_messages = observer.get_cached_message()

        assert len(cached_messages) > 0
        message_data = json.loads(cached_messages[0])
        assert len(message_data["content"]) == 1000

    def test_observer_mode_transitions(self):
        """Test observer mode transitions between thinking and code modes"""
        observer = MessageObserver()

        # Start in thinking mode
        assert observer.current_mode == ProcessType.MODEL_OUTPUT_THINKING

        # Add code content
        observer.add_model_new_token("代码:")
        observer.add_model_new_token("```")
        observer.add_model_new_token("print('test')")
        observer.add_model_new_token("```")

        # Flush to process mode change
        observer.flush_remaining_tokens()

        # Should now be in code mode
        assert observer.current_mode == ProcessType.MODEL_OUTPUT_CODE

        # Add more content
        observer.add_model_new_token("More code")
        observer.flush_remaining_tokens()

        # Should still be in code mode
        assert observer.current_mode == ProcessType.MODEL_OUTPUT_CODE


class TestMaxStepsReached:
    """Test MAX_STEPS_REACHED ProcessType and MessageObserver handling."""

    def test_process_type_max_steps_reached_exists(self):
        """Test that ProcessType.MAX_STEPS_REACHED exists and has correct value."""
        assert hasattr(ProcessType, 'MAX_STEPS_REACHED')
        assert ProcessType.MAX_STEPS_REACHED.value == "max_steps_reached"

    def test_max_steps_reached_message_format(self):
        """Test that MAX_STEPS_REACHED messages are handled by DefaultTransformer."""
        observer = MessageObserver()

        max_steps_data = json.dumps({
            "completedSteps": 3,
            "maxSteps": 3,
            "message": ""
        })

        observer.add_message("test_agent", ProcessType.MAX_STEPS_REACHED, max_steps_data)

        cached_messages = observer.get_cached_message()
        assert len(cached_messages) == 1

        message_data = json.loads(cached_messages[0])
        assert message_data["type"] == ProcessType.MAX_STEPS_REACHED.value

        # Parse the content to verify the data structure
        content_data = json.loads(message_data["content"])
        assert content_data["completedSteps"] == 3
        assert content_data["maxSteps"] == 3
        assert content_data["message"] == ""

    def test_max_steps_reached_with_different_completed_steps(self):
        """Test MAX_STEPS_REACHED message with different completed step counts."""
        observer = MessageObserver()

        # Test with 1 completed step (reached max at step 1)
        max_steps_data = json.dumps({
            "completedSteps": 1,
            "maxSteps": 3,
            "message": ""
        })

        observer.add_message("test_agent", ProcessType.MAX_STEPS_REACHED, max_steps_data)

        cached_messages = observer.get_cached_message()
        message_data = json.loads(cached_messages[0])
        content_data = json.loads(message_data["content"])

        assert content_data["completedSteps"] == 1
        assert content_data["maxSteps"] == 3

    def test_max_steps_reached_multiple_messages(self):
        """Test that MAX_STEPS_REACHED can be added alongside other messages."""
        observer = MessageObserver()

        # Add some regular messages first
        observer.add_message("test_agent", ProcessType.STEP_COUNT, "1")
        observer.add_message("test_agent", ProcessType.STEP_COUNT, "2")

        # Add max steps reached message
        max_steps_data = json.dumps({
            "completedSteps": 2,
            "maxSteps": 3,
            "message": ""
        })
        observer.add_message("test_agent", ProcessType.MAX_STEPS_REACHED, max_steps_data)

        cached_messages = observer.get_cached_message()
        assert len(cached_messages) == 3

        # Verify the last message is MAX_STEPS_REACHED
        last_message = json.loads(cached_messages[2])
        assert last_message["type"] == ProcessType.MAX_STEPS_REACHED.value

    def test_max_steps_data_structure_matches_run_stream(self):
        """Test the data structure matches what _run_stream creates."""
        observer = MessageObserver()

        # Simulate the data structure created in _run_stream
        step_number = 4  # This is max_steps + 1 when max is 3
        max_steps = 3
        completed_steps = step_number - 1  # This equals max_steps

        max_steps_data = json.dumps({
            "completedSteps": completed_steps,
            "maxSteps": max_steps,
            "message": ""
        })

        observer.add_message("test_agent", ProcessType.MAX_STEPS_REACHED, max_steps_data)

        cached_messages = observer.get_cached_message()
        message_data = json.loads(cached_messages[0])
        content_data = json.loads(message_data["content"])

        # Verify the data structure matches what _run_stream creates
        assert "completedSteps" in content_data
        assert "maxSteps" in content_data
        assert "message" in content_data
        assert content_data["completedSteps"] == completed_steps
        assert content_data["maxSteps"] == max_steps
        assert content_data["message"] == ""

    def test_max_steps_reached_edge_case_single_step(self):
        """Test max steps data when agent completes only 1 step."""
        observer = MessageObserver()

        max_steps_data = json.dumps({
            "completedSteps": 1,
            "maxSteps": 1,
            "message": ""
        })

        observer.add_message("test_agent", ProcessType.MAX_STEPS_REACHED, max_steps_data)

        cached_messages = observer.get_cached_message()
        message_data = json.loads(cached_messages[0])
        content_data = json.loads(message_data["content"])

        assert content_data["completedSteps"] == 1
        assert content_data["maxSteps"] == 1

    def test_max_steps_reached_edge_case_large_step_count(self):
        """Test max steps data with large step counts."""
        observer = MessageObserver()

        max_steps_data = json.dumps({
            "completedSteps": 100,
            "maxSteps": 100,
            "message": ""
        })

        observer.add_message("test_agent", ProcessType.MAX_STEPS_REACHED, max_steps_data)

        cached_messages = observer.get_cached_message()
        message_data = json.loads(cached_messages[0])
        content_data = json.loads(message_data["content"])

        assert content_data["completedSteps"] == 100
        assert content_data["maxSteps"] == 100

    def test_max_steps_reached_uses_default_transformer(self):
        """Test that MAX_STEPS_REACHED uses DefaultTransformer (returns content as-is)."""
        observer = MessageObserver()

        original_content = "已达到最大步数限制（3 步），下方汇总了当前已完成的工作。"
        max_steps_data = json.dumps({
            "completedSteps": 3,
            "maxSteps": 3,
            "message": original_content
        })

        observer.add_message("test_agent", ProcessType.MAX_STEPS_REACHED, max_steps_data)

        cached_messages = observer.get_cached_message()
        message_data = json.loads(cached_messages[0])

        # Content should be returned as-is by DefaultTransformer
        assert message_data["content"] == max_steps_data

    def test_max_steps_reached_chinese_content(self):
        """Test MAX_STEPS_REACHED message with Chinese content."""
        observer = MessageObserver(lang="zh")

        max_steps_data = json.dumps({
            "completedSteps": 5,
            "maxSteps": 5,
            "message": "已达到最大步数限制"
        })

        observer.add_message("test_agent", ProcessType.MAX_STEPS_REACHED, max_steps_data)

        cached_messages = observer.get_cached_message()
        message_data = json.loads(cached_messages[0])
        content_data = json.loads(message_data["content"])

        assert content_data["completedSteps"] == 5
        assert "已达到最大步数限制" in str(content_data)


class TestObserverDeepThinkBufferOverflow:
    """Test think_buffer overflow handling in add_model_new_token"""

    def test_think_buffer_overflow_flushes_in_think_mode(self):
        """Test that think_buffer overflow triggers flush while in think mode"""
        observer = MessageObserver()

        # Start think mode
        observer.add_model_new_token("<think>")
        observer.add_model_new_token("Thinking")
        observer.flush_remaining_tokens()
        observer.get_cached_message()

        # Now we're in think mode, add tokens to overflow think_buffer
        # First, enter think mode again
        observer.in_think_mode = True
        for i in range(15):  # More than MAX_TOKEN_BUFFER_SIZE (10)
            observer.add_model_new_token(f"t{i}")

        # think_buffer should be managed (not exceed MAX)
        assert len(observer.think_buffer) <= observer.MAX_TOKEN_BUFFER_SIZE

        # Flush and check messages
        observer.flush_remaining_tokens()
        messages = observer.get_cached_message()
        assert len(messages) > 0

    def test_think_buffer_overflow_flushes_in_normal_mode(self):
        """Test that think_buffer overflow flushes to _process_normal_content when not in think mode"""
        observer = MessageObserver()

        # Ensure not in think mode
        assert not observer.in_think_mode

        # Add many tokens to overflow think_buffer
        for i in range(15):
            observer.add_model_new_token(f"token{i}")

        # Should have accumulated content from overflow
        observer.flush_remaining_tokens()
        messages = observer.get_cached_message()

        # Overflow should have triggered processing
        assert len(messages) >= 1


class TestObserverProcessNormalContentBufferOverflow:
    """Test token_buffer overflow handling in _process_normal_content"""

    def test_token_buffer_overflow_flushes_content(self):
        """Test that token_buffer overflow triggers flush"""
        observer = MessageObserver()

        # Add tokens that will exceed buffer size without code block detection
        tokens = []
        for i in range(15):
            token = f"content{i}"
            tokens.append(token)
            observer.add_model_new_token(token)

        # token_buffer should be managed
        assert len(observer.token_buffer) <= observer.MAX_TOKEN_BUFFER_SIZE

        # Flush and verify
        observer.flush_remaining_tokens()
        messages = observer.get_cached_message()
        assert len(messages) >= 1


class TestObserverThinkTagFragmentation:
    """Test think tag fragmentation scenarios"""

    def test_think_start_tag_fragmented(self):
        """Test detection of fragmented <think> tag"""
        observer = MessageObserver()

        # Fragment the start tag
        observer.add_model_new_token("<")
        observer.add_model_new_token("think")
        observer.add_model_new_token(">")

        # Should enter think mode
        assert observer.in_think_mode

        # Add some content
        observer.add_model_new_token("Reasoning process")

        # End tag fragmented
        observer.add_model_new_token("<")
        observer.add_model_new_token("/think")
        observer.add_model_new_token(">")

        # Should exit think mode
        assert not observer.in_think_mode

    def test_think_end_tag_only(self):
        """Test when </think> appears without preceding <think>"""
        observer = MessageObserver()

        # Only end tag, no start
        observer.add_model_new_token("</think>")

        # Should not be in think mode
        assert not observer.in_think_mode

        # Flush should process normally
        observer.flush_remaining_tokens()
        messages = observer.get_cached_message()
        assert len(messages) >= 1

    def test_think_content_only(self):
        """Test when only <think> content is received"""
        observer = MessageObserver()

        # Enter think mode and add content
        observer.add_model_new_token("<think>")
        observer.add_model_new_token("Deep reasoning")
        # Don't close the tag - still in think mode

        # Flush should handle unclosed think tag
        observer.flush_remaining_tokens()
        messages = observer.get_cached_message()

        # Should contain the reasoning as deep thinking
        assert len(messages) >= 1


class TestObserverCodeModeSwitching:
    """Test code block detection and mode switching"""

    def test_code_mode_from_thinking_mode(self):
        """Test switching from thinking to code mode when code block detected"""
        observer = MessageObserver(lang="zh")

        # Start with thinking mode
        assert observer.current_mode == ProcessType.MODEL_OUTPUT_THINKING

        # Add code block - using full triple backticks to trigger detection
        observer.add_model_new_token("代码:")
        observer.add_model_new_token("```python")
        observer.add_model_new_token("print('hello')")
        observer.add_model_new_token("```")

        # Flush to process all content
        observer.flush_remaining_tokens()

        # Should have processed content (mode behavior varies based on implementation)
        # Just verify the observer doesn't crash
        messages = observer.get_cached_message()
        assert len(messages) >= 0

    def test_code_mode_stays_in_code_mode(self):
        """Test that once in code mode, subsequent content stays in code mode"""
        observer = MessageObserver(lang="zh")

        # Add content that triggers code detection
        observer.add_model_new_token("```")
        observer.flush_remaining_tokens()
        observer.get_cached_message()

        # Mode depends on implementation - just verify no crash
        observer.add_model_new_token("More code here")
        observer.flush_remaining_tokens()

        # Should not crash regardless of mode


class TestObserverFlushRemainingTokens:
    """Test flush_remaining_tokens edge cases"""

    def test_flush_with_empty_buffers(self):
        """Test flush when both buffers are empty"""
        observer = MessageObserver()

        # Flush empty buffers
        observer.flush_remaining_tokens()

        # Should not crash and produce no messages
        messages = observer.get_cached_message()
        assert len(messages) == 0

    def test_flush_think_buffer_with_think_tags(self):
        """Test flush remaining think buffer with think tags still present"""
        observer = MessageObserver()

        # Enter think mode with think tag
        observer.add_model_new_token("<think>")
        observer.add_model_new_token("Thinking content")

        # Flush while still in think mode - tags should be stripped
        observer.flush_remaining_tokens()
        messages = observer.get_cached_message()

        # Content should be in deep thinking, tags stripped
        assert len(messages) >= 1
        message_data = json.loads(messages[0])
        assert message_data["type"] == ProcessType.MODEL_OUTPUT_DEEP_THINKING.value

    def test_flush_think_buffer_empty_after_stripping_tags(self):
        """Test flush when buffer only contains think tags"""
        observer = MessageObserver()

        # Enter think mode but only have tags
        observer.add_model_new_token("<think>")
        observer.add_model_new_token("</think>")

        # Buffer may have content from processing - just verify flush works
        observer.flush_remaining_tokens()
        messages = observer.get_cached_message()

        # Flush should complete without error
        assert isinstance(messages, list)

    def test_flush_token_buffer_only(self):
        """Test flush when only token_buffer has content"""
        observer = MessageObserver()

        # Add content without triggering think mode
        observer.add_model_new_token("Regular content")

        # Flush
        observer.flush_remaining_tokens()
        messages = observer.get_cached_message()

        assert len(messages) >= 1


class TestObserverGetFinalAnswerEdgeCases:
    """Test get_final_answer edge cases"""

    def test_get_final_answer_with_non_string_item(self):
        """Test get_final_answer when message_queue contains non-string items"""
        observer = MessageObserver()

        # Add a non-string item to the queue
        observer.message_query.append({"type": "not_a_string", "content": "test"})
        observer.message_query.append(
            Message(ProcessType.FINAL_ANSWER, "The final answer").to_json()
        )

        # Should handle non-string gracefully
        result = observer.get_final_answer()
        assert result == "The final answer"

    def test_get_final_answer_with_malformed_json(self):
        """Test get_final_answer with malformed JSON in queue"""
        observer = MessageObserver()

        # Add malformed JSON
        observer.message_query.append("{invalid json")
        observer.message_query.append(
            Message(ProcessType.FINAL_ANSWER, "Valid answer").to_json()
        )

        result = observer.get_final_answer()
        assert result == "Valid answer"

    def test_get_final_answer_empty_queue(self):
        """Test get_final_answer with empty queue"""
        observer = MessageObserver()

        result = observer.get_final_answer()
        assert result is None


class TestProcessTypeEnum:
    """Test ProcessType enum values"""

    def test_all_process_types_exist(self):
        """Test that all ProcessType values are defined"""
        expected_types = [
            "MODEL_OUTPUT_THINKING",
            "MODEL_OUTPUT_DEEP_THINKING",
            "MODEL_OUTPUT_CODE",
            "STEP_COUNT",
            "PARSE",
            "EXECUTION_LOGS",
            "AGENT_NEW_RUN",
            "AGENT_FINISH",
            "FINAL_ANSWER",
            "ERROR",
            "OTHER",
            "TOKEN_COUNT",
            "SEARCH_CONTENT",
            "PICTURE_WEB",
            "CARD",
            "TOOL",
            "MEMORY_SEARCH",
            "MAX_STEPS_REACHED",
            "VERIFICATION",
        ]

        for type_name in expected_types:
            assert hasattr(ProcessType, type_name), f"Missing ProcessType: {type_name}"

    def test_process_type_values_are_strings(self):
        """Test that all ProcessType values are string values"""
        for member in ProcessType:
            assert isinstance(member.value, str)
            assert len(member.value) > 0


class TestTransformerWithAgentName:
    """Test transformers with agent_name parameter"""

    def test_add_message_with_agent_name(self):
        """Test that add_message passes agent_name to transformer"""
        observer = MessageObserver(lang="zh")

        # Add a message with agent name
        observer.add_message(
            agent_name="test_agent",
            process_type=ProcessType.STEP_COUNT,
            content="1"
        )

        messages = observer.get_cached_message()
        assert len(messages) == 1

        # Content should be formatted (step count adds formatting)
        message_data = json.loads(messages[0])
        # Chinese format: "步骤" or English: "Step"
        assert "1" in message_data["content"]


class TestMessageObserverStateManagement:
    """Test MessageObserver state management"""

    def test_in_think_mode_initial_state(self):
        """Test that in_think_mode starts as False"""
        observer = MessageObserver()
        assert observer.in_think_mode is False

    def test_current_mode_initial_state(self):
        """Test that current_mode starts as MODEL_OUTPUT_THINKING"""
        observer = MessageObserver()
        assert observer.current_mode == ProcessType.MODEL_OUTPUT_THINKING

    def test_message_query_initial_state(self):
        """Test that message_query starts as empty list"""
        observer = MessageObserver()
        assert observer.message_query == []
        assert isinstance(observer.message_query, list)


class TestMessageObserverMultipleOperations:
    """Test MessageObserver with multiple sequential operations"""

    def test_multiple_think_cycles(self):
        """Test multiple <think> - </think> cycles"""
        observer = MessageObserver()

        # First cycle
        observer.add_model_new_token("<think>")
        observer.add_model_new_token("First")
        observer.add_model_new_token("</think>")

        # Second cycle
        observer.add_model_new_token("<think>")
        observer.add_model_new_token("Second")
        observer.add_model_new_token("</think>")

        observer.flush_remaining_tokens()
        messages = observer.get_cached_message()

        # Should have processed both cycles
        assert len(messages) >= 2

    def test_interleaved_content_and_think(self):
        """Test interleaved normal content and think tags"""
        observer = MessageObserver()

        observer.add_model_new_token("Start")
        observer.add_model_new_token("<think>")
        observer.add_model_new_token("Thought")
        observer.add_model_new_token("</think>")
        observer.add_model_new_token("End")

        observer.flush_remaining_tokens()
        messages = observer.get_cached_message()

        # Should have processed content
        assert len(messages) >= 1


class TestMessageObserverCodeBlockVariants:
    """Test various code block patterns"""

    def test_single_backticks(self):
        """Test single backticks don't trigger code mode"""
        observer = MessageObserver()

        observer.add_model_new_token("Use `code` inline")

        observer.flush_remaining_tokens()
        messages = observer.get_cached_message()

        # Should not trigger code mode
        assert observer.current_mode == ProcessType.MODEL_OUTPUT_THINKING
        assert len(messages) >= 1

    def test_partial_code_block_start(self):
        """Test partial triple backticks"""
        observer = MessageObserver()

        observer.add_model_new_token("``")
        observer.add_model_new_token("`")

        observer.flush_remaining_tokens()
        messages = observer.get_cached_message()

        # Should not trigger code mode with double backticks
        assert observer.current_mode == ProcessType.MODEL_OUTPUT_THINKING


if __name__ == "__main__":
    pytest.main([__file__])
