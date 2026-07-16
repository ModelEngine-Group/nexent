"""
Unit tests for ContextManager fingerprinting, normalization, and change detection.

Covers the largest untested blocks in manager.py:
- _normalize_for_fingerprint (lines 605-626)
- _fingerprint (lines 631-638)
- _stable_component_fingerprints (lines 645-658)
- _change_reasons (lines 663-682)
- _purpose_messages (lines 541-555)
- _messages_from_memory (lines 562-567)
- _without_leading_stable_messages (lines 571-574)
- _canonical_tools (lines 578-582)
- _estimate_tools_tokens (lines 597-599)
- build_compressed_snapshot (lines 379-403)
- init keep_recent_steps cap (line 67)
- token estimation delegates (lines 349, 352, 355)
"""

from loader import (
    ContextManager, ContextManagerConfig, TaskStep, ActionStep,
    AgentMemory, ChatMessage, MessageRole, SystemPromptStep,
    SummaryTaskStep, extract_message_text, message_role,
)


# ── Helpers ──────────────────────────────────────────────────

def _make_memory(steps=None, system_prompt="You are helpful."):
    memory = AgentMemory()
    if system_prompt:
        memory.system_prompt = SystemPromptStep(system_prompt=system_prompt)
    if steps:
        memory.steps = steps
    return memory


def _make_chat_message(role, text):
    return ChatMessage(role=role, content=[{"type": "text", "text": text}])


class MockTool:
    def __init__(self, name="search"):
        self.name = name

    def __repr__(self):
        return f"MockTool({self.name!r})"


class MockComponent:
    def __init__(self, component_type="test", content="", priority=10):
        self.component_type = component_type
        self.priority = priority
        self._content = content

    def to_messages(self):
        if self._content:
            return [{"role": "system", "content": self._content}]
        return []

    def estimate_tokens(self, chars_per_token=1.5):
        return int(len(self._content) / chars_per_token)


# ── Init edge case ───────────────────────────────────────────

class TestInitKeepRecentStepsCap:
    def test_keep_recent_steps_capped_to_max_steps(self):
        config = ContextManagerConfig(keep_recent_steps=20)
        cm = ContextManager(config=config, max_steps=5)
        assert cm.config.keep_recent_steps == 5

    def test_keep_recent_steps_uncapped_when_below_max_steps(self):
        config = ContextManagerConfig(keep_recent_steps=3)
        cm = ContextManager(config=config, max_steps=10)
        assert cm.config.keep_recent_steps == 3

    def test_no_cap_when_max_steps_is_none(self):
        config = ContextManagerConfig(keep_recent_steps=100)
        cm = ContextManager(config=config, max_steps=None)
        assert cm.config.keep_recent_steps == 100


# ── Token estimation delegates ───────────────────────────────

class TestTokenEstimationDelegates:
    def test_estimate_tokens_for_steps(self):
        cm = ContextManager()
        step = ActionStep(model_output="hello world", action_output="done")
        result = cm._estimate_tokens_for_steps([step])
        assert isinstance(result, int)
        assert result > 0

    def test_estimate_tokens_for_memory(self):
        cm = ContextManager()
        memory = _make_memory(steps=[TaskStep(task="do something")])
        result = cm._estimate_tokens(memory)
        assert isinstance(result, int)

    def test_msg_char_count(self):
        cm = ContextManager()
        msg = _make_chat_message(MessageRole.USER, "hello")
        result = cm._msg_char_count(msg)
        assert result == 5


# ── _normalize_for_fingerprint ───────────────────────────────

class TestNormalizeForFingerprint:
    def test_dict_sorted_and_normalized(self):
        result = ContextManager._normalize_for_fingerprint({"z": 1, "a": 2})
        assert list(result.keys()) == ["a", "z"]

    def test_list_normalized(self):
        result = ContextManager._normalize_for_fingerprint([3, 1, 2])
        assert result == [3, 1, 2]

    def test_primitive_values_passthrough(self):
        for val in ["str", 42, 3.14, True, None]:
            assert ContextManager._normalize_for_fingerprint(val) == val

    def test_object_with_name(self):
        result = ContextManager._normalize_for_fingerprint(MockTool("search"))
        assert result == {"__class__": "MockTool", "name": "search"}

    def test_object_with_model_dump(self):
        class Dumpable:
            def model_dump(self):
                return {"key": "val"}
        result = ContextManager._normalize_for_fingerprint(Dumpable())
        assert result == {"key": "val"}

    def test_object_with_public_attrs(self):
        class AttrObj:
            def __init__(self):
                self.x = 1
                self._private = 2
        result = ContextManager._normalize_for_fingerprint(AttrObj())
        assert result == {"x": 1}

    def test_object_with_no_recognizable_attrs(self):
        result = ContextManager._normalize_for_fingerprint(object())
        assert "__class__" in result

    def test_nested_dict(self):
        result = ContextManager._normalize_for_fingerprint({"b": {"c": 1}, "a": 2})
        assert list(result.keys()) == ["a", "b"]
        assert result["b"] == {"c": 1}

    def test_tuple_normalized_to_list(self):
        result = ContextManager._normalize_for_fingerprint((1, 2, 3))
        assert result == [1, 2, 3]


# ── _fingerprint ─────────────────────────────────────────────

class TestFingerprint:
    def test_deterministic(self):
        data = [{"role": "system", "content": "test"}]
        fp1 = ContextManager()._fingerprint(data)
        fp2 = ContextManager()._fingerprint(data)
        assert fp1 == fp2

    def test_different_data_different_fingerprint(self):
        fp1 = ContextManager()._fingerprint([{"role": "system"}])
        fp2 = ContextManager()._fingerprint([{"role": "user"}])
        assert fp1 != fp2

    def test_returns_hex_string(self):
        fp = ContextManager()._fingerprint(["test"])
        assert isinstance(fp, str)
        assert all(c in "0123456789abcdef" for c in fp)


# ── _change_reasons ──────────────────────────────────────────

class TestChangeReasons:
    def test_initial_request(self):
        cm = ContextManager()
        reasons = cm._change_reasons("abc123", {})
        assert reasons == ["initial_request"]

    def test_no_change_when_fingerprint_matches(self):
        cm = ContextManager()
        cm._previous_stable_fingerprint = "abc"
        cm._previous_stable_components = {}
        reasons = cm._change_reasons("abc", {})
        assert reasons == []

    def test_tool_schema_version_change(self):
        cm = ContextManager()
        cm._previous_stable_fingerprint = "old"
        cm._previous_stable_components = {"tools": "fp1"}
        reasons = cm._change_reasons("new", {"tools": "fp2"})
        assert "tool_schema_version" in reasons

    def test_context_purpose_change(self):
        cm = ContextManager()
        cm._previous_stable_fingerprint = "old"
        cm._previous_stable_components = {"purpose": "fp1"}
        reasons = cm._change_reasons("new", {"purpose": "fp2"})
        assert "context_purpose" in reasons

    def test_system_prompt_version_change(self):
        cm = ContextManager()
        cm._previous_stable_fingerprint = "old"
        cm._previous_stable_components = {"system_prompt": "fp1"}
        reasons = cm._change_reasons("new", {"system_prompt": "fp2"})
        assert "system_prompt_version" in reasons

    def test_unexpected_nondeterminism_when_only_fingerprint_diffs(self):
        cm = ContextManager()
        cm._previous_stable_fingerprint = "old"
        cm._previous_stable_components = {"tools": "same_fp"}
        reasons = cm._change_reasons("new", {"tools": "same_fp"})
        assert reasons == ["unexpected_nondeterminism"]


# ── _purpose_messages ────────────────────────────────────────

class TestPurposeMessages:
    def test_non_final_answer_returns_empty(self):
        cm = ContextManager()
        stable, dynamic = cm._purpose_messages(
            purpose="step", task=None, final_answer_templates=None
        )
        assert stable == [] and dynamic == []

    def test_final_answer_without_templates_raises(self):
        cm = ContextManager()
        try:
            cm._purpose_messages(
                purpose="final_answer", task="test",
                final_answer_templates=None
            )
            assert False, "Expected ValueError"
        except ValueError:
            pass

    def test_final_answer_with_valid_template(self):
        cm = ContextManager()
        templates = {
            "final_answer": {
                "pre_messages": "Wrap up now.",
                "post_messages": "Answer: {{ task }}",
            }
        }
        stable, dynamic = cm._purpose_messages(
            purpose="final_answer", task="compute 2+2",
            final_answer_templates=templates
        )
        assert len(stable) == 1
        assert len(dynamic) == 1
        assert "compute 2+2" in dynamic[0]["content"][0]["text"]

    def test_final_answer_template_missing_keys_raises(self):
        cm = ContextManager()
        templates = {"final_answer": {"pre_messages": "ok"}}
        try:
            cm._purpose_messages(
                purpose="final_answer", task="x",
                final_answer_templates=templates
            )
            assert False, "Expected ValueError"
        except ValueError:
            pass


# ── _messages_from_memory ────────────────────────────────────

class TestMessagesFromMemory:
    def test_empty_memory(self):
        memory = _make_memory(system_prompt=None, steps=[])
        result = ContextManager._messages_from_memory(memory)
        assert result == []

    def test_system_prompt_only(self):
        memory = _make_memory(system_prompt="hello", steps=[])
        result = ContextManager._messages_from_memory(memory)
        assert len(result) > 0

    def test_with_steps(self):
        step = TaskStep(task="do it")
        memory = _make_memory(steps=[step])
        result = ContextManager._messages_from_memory(memory)
        assert len(result) >= 1

    def test_system_and_steps_combined(self):
        step = TaskStep(task="go")
        memory = _make_memory(system_prompt="sys", steps=[step])
        result = ContextManager._messages_from_memory(memory)
        assert len(result) >= 2


# ── _without_leading_stable_messages ─────────────────────────

class TestWithoutLeadingStableMessages:
    def test_empty_list(self):
        result = ContextManager._without_leading_stable_messages([])
        assert result == []

    def test_no_leading_system(self):
        msgs = [{"role": "user", "content": "hi"}]
        result = ContextManager._without_leading_stable_messages(msgs)
        assert result == msgs

    def test_strips_leading_system(self):
        msgs = [
            {"role": "system", "content": "sys1"},
            {"role": "developer", "content": "dev1"},
            {"role": "user", "content": "hi"},
        ]
        result = ContextManager._without_leading_stable_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_all_system_messages(self):
        msgs = [
            {"role": "system", "content": "s1"},
            {"role": "system", "content": "s2"},
        ]
        result = ContextManager._without_leading_stable_messages(msgs)
        assert result == []

    def test_system_in_middle_not_stripped(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "system", "content": "mid"},
        ]
        result = ContextManager._without_leading_stable_messages(msgs)
        assert len(result) == 2


# ── _canonical_tools ─────────────────────────────────────────

class TestCanonicalTools:
    def test_empty_tools(self):
        result = ContextManager._canonical_tools([])
        assert result == []

    def test_single_tool(self):
        result = ContextManager._canonical_tools([MockTool("search")])
        assert len(result) == 1

    def test_tools_sorted_by_name_then_index(self):
        t1 = MockTool("zebra")
        t2 = MockTool("alpha")
        result = ContextManager._canonical_tools([t1, t2])
        names = [getattr(t, "name", None) for t in result]
        assert names == ["alpha", "zebra"]


# ── _estimate_tools_tokens ───────────────────────────────────

class TestEstimateToolsTokens:
    def test_empty_tools_returns_zero(self):
        cm = ContextManager()
        assert cm._estimate_tools_tokens([]) == 0

    def test_tools_returns_positive(self):
        cm = ContextManager()
        result = cm._estimate_tools_tokens([MockTool("search")])
        assert result > 0


# ── _stable_component_fingerprints ───────────────────────────

class TestStableComponentFingerprints:
    def test_no_components(self):
        cm = ContextManager()
        result = cm._stable_component_fingerprints(components=[])
        assert result == {}

    def test_component_with_system_messages(self):
        cm = ContextManager()
        comp = MockComponent(component_type="system_prompt", content="sys text")
        result = cm._stable_component_fingerprints(components=[comp])
        assert "system_prompt" in result
        assert isinstance(result["system_prompt"], str)

    def test_component_without_stable_messages_skipped(self):
        class DynComp:
            component_type = "dynamic"
            def to_messages(self):
                return [{"role": "user", "content": "dynamic"}]
        cm = ContextManager()
        result = cm._stable_component_fingerprints(components=[DynComp()])
        assert "dynamic" not in result

    def test_purpose_stable_included(self):
        cm = ContextManager()
        purpose_stable = [{"role": "system", "content": "purpose"}]
        result = cm._stable_component_fingerprints(purpose_stable=purpose_stable)
        assert "purpose" in result

    def test_component_without_to_messages_skipped(self):
        class NoMsgComp:
            component_type = "nomsg"
        cm = ContextManager()
        result = cm._stable_component_fingerprints(components=[NoMsgComp()])
        assert "nomsg" not in result


# ── build_compressed_snapshot ────────────────────────────────

class TestBuildCompressedSnapshot:
    def test_preserves_cache_state_after_call(self):
        cm = ContextManager()
        cm._previous_summary_cache = "saved_prev"
        cm._current_summary_cache = "saved_curr"
        cm._step_local_log = ["log1"]
        cm.compression_calls_log = ["call1"]

        memory = _make_memory(steps=[])
        try:
            cm.build_compressed_snapshot(model=None, memory=memory, current_run_start_idx=0)
        except Exception:
            pass

        assert cm._previous_summary_cache == "saved_prev"
        assert cm._current_summary_cache == "saved_curr"
        assert cm._step_local_log == ["log1"]
        assert cm.compression_calls_log == ["call1"]

    def test_returns_messages_and_metadata(self):
        cm = ContextManager()
        memory = _make_memory(steps=[])
        result = cm.build_compressed_snapshot(model=None, memory=memory, current_run_start_idx=0)
        assert isinstance(result, tuple)
        assert len(result) == 2
        _, metadata = result
        assert isinstance(metadata, dict)
        assert "token_counts" in metadata


if __name__ == "__main__":
    import pytest
    pytest.main([__file__])
