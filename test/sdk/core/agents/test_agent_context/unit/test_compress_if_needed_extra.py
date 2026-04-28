"""
unit/test_compress_if_needed_extra.py
Supplementary branch coverage for TestCompressIfNeeded.

Existing tests cover:
  G1 disabled / under-threshold / run-boundary / G2 both-cache / G2 prev-only /
  G2 curr-only / main-path prev+curr both compress / main-path mixed

This file adds (corresponding to branch diagram M1-M13):
  M1  First call _last_run_start_idx=None -> no exception, no cache clear
  M2  G2 shortcut no cache: return raw messages (no LLM call)
  M3  compress_prev=True but pairs_to_compress empty (keep_n >= all pairs)
  M4  compress_prev=True, LLM returns None -> raw prev displayed, no crash
  M5  compress_prev=False with valid prev cache -> main path applies cache (not G2)
  M6  compress_curr=True but actions_to_compress empty
  M7  compress_curr=True, LLM returns None -> raw curr displayed, no crash
  M8  compress_curr=False with valid curr cache -> main path applies cache (not G2)
  M9  Only current-run (current_run_start_idx=0), no previous, over threshold, no cache
  M10 keep_recent_pairs exceeds total pairs boundary handling
  M11 prev+curr both LLM fail -> result still list, no crash
  M12 No system_prompt -> no system message in result
  M13 Each compress call clears _step_local_log
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from unittest.mock import MagicMock, patch

from factories import make_cm, make_pair, make_model, make_original_messages
from loader import (
    ActionStep,
    AgentMemory,
    ContextManager,
    ContextManagerConfig,
    CurrentSummaryCache,
    PreviousSummaryCache,
    SummaryTaskStep,
    TaskStep,
)
from stubs import _SystemPromptStep as SystemPromptStep


def _all_texts(messages):
    return [
        b.get("text", "")
        for m in messages
        for b in (m.content if isinstance(m.content, list) else [])
        if isinstance(b, dict)
    ]


def _joined(messages):
    return " ".join(_all_texts(messages))


class TestM1FirstCall:

    def test_first_call_no_exception_and_no_cache_clear(self):
        """Initial state _last_run_start_idx=None, first call should not clear current cache."""
        cm = make_cm(enabled=True, threshold=999999)
        cm._current_summary_cache = CurrentSummaryCache("existing summary", 1, "fp")
        assert cm._last_run_start_idx is None

        t, a = make_pair("task", "action", 0)
        memory = AgentMemory(steps=[t, a], system_prompt=None)
        original = make_original_messages(memory)

        result = cm.compress_if_needed(None, memory, original, current_run_start_idx=2)

        assert result is original
        assert cm._current_summary_cache is not None


class TestM2G2NoCacheRawReturn:

    def test_g2_shortcut_no_cache_returns_raw_messages(self):
        """effective <= threshold but no cache, should use _build_messages to assemble raw steps."""
        cm = make_cm(enabled=True, threshold=10)
        t, a = make_pair("x", "y", 0)
        memory = AgentMemory(steps=[t, a], system_prompt=None)
        original = make_original_messages(memory)

        with patch.object(cm, '_estimate_tokens', return_value=50):
            with patch.object(cm, '_effective_tokens', return_value=5):
                model = make_model()
                result = cm.compress_if_needed(model, memory, original, current_run_start_idx=2)

        model.assert_not_called()
        assert isinstance(result, list)
        assert "Summary of earlier steps" not in _joined(result)
        assert "x" in _joined(result)


class TestM3PairsToCompressEmpty:

    def test_compress_prev_true_but_all_pairs_kept_no_llm(self):
        """keep_recent_pairs >= len(pairs), pairs_to_compress=[], should not call LLM.
        All pairs retained in raw form.
        """
        cm = make_cm(enabled=True, threshold=1, keep_recent_pairs=10)
        t0, a0 = make_pair("task0 " + "X" * 50, "action0 " + "Y" * 50, 0)
        t1, a1 = make_pair("task1 " + "X" * 50, "action1 " + "Y" * 50, 1)
        memory = AgentMemory(steps=[t0, a0, t1, a1], system_prompt=None)
        original = make_original_messages(memory)

        model = make_model('{"task_overview": "summary"}')
        result = cm.compress_if_needed(model, memory, original, current_run_start_idx=4)

        model.assert_not_called()
        assert isinstance(result, list)
        assert "task0" in _joined(result)
        assert "task1" in _joined(result)


class TestM4PrevLLMReturnsNone:

    def test_prev_llm_returns_none_raw_steps_shown(self):
        """When _compress_previous_with_cache returns None, prev_summary_step=None,
        raw prev steps appear in result, no crash.
        """
        cm = make_cm(enabled=True, threshold=1, keep_recent_pairs=1)
        t0, a0 = make_pair("task0 " + "X" * 50, "action0 " + "Y" * 50, 0)
        t1, a1 = make_pair("task1 " + "X" * 50, "action1 " + "Y" * 50, 1)
        memory = AgentMemory(steps=[t0, a0, t1, a1], system_prompt=None)
        original = make_original_messages(memory)

        with patch.object(cm, '_compress_previous_with_cache', return_value=None):
            model = make_model()
            result = cm.compress_if_needed(model, memory, original, current_run_start_idx=4)

        assert isinstance(result, list)
        assert "Summary of earlier steps" not in _joined(result)
        assert "task1" in _joined(result)


class TestM5PrevCacheInMainPath:

    def test_compress_prev_false_with_valid_cache_applied_in_main_path(self):
        """
        Scenario: effective_tokens > threshold (enter main path),
        but prev_tokens <= threshold*0.6 (compress_prev=False),
        and prev cache valid -> elif branch applies prev cache.
        Different from G2 shortcut: G2 is effective <= threshold short-circuit.
        """
        cm = make_cm(enabled=True, threshold=100, keep_recent_pairs=1)

        t, a = make_pair("prev_task" + "X" * 200, "prev_action" + "Y" * 200, 0)
        curr_t, curr_a = make_pair("curr_task " + "X" * 200, "curr_action " + "Y" * 200, 1)
        memory = AgentMemory(
            steps=[t, a, curr_t, curr_a],
            system_prompt=SystemPromptStep(system_prompt="sys"),
        )

        fp = cm._pair_fingerprint(t.task, a.action_output)
        cm._previous_summary_cache = PreviousSummaryCache("prev_cached_summary", 1, fp)

        def mock_effective_prev(steps):
            return 40

        def mock_effective_curr(steps):
            return 80

        with patch.object(cm, '_effective_prev_tokens', side_effect=mock_effective_prev):
            with patch.object(cm, '_effective_curr_tokens', side_effect=mock_effective_curr):
                model = make_model('{"task_overview": "curr_summary"}')
                original = make_original_messages(memory)
                result = cm.compress_if_needed(model, memory, original, current_run_start_idx=2)
        texts = _all_texts(result)
        assert any("prev_cached_summary" in t for t in texts)
        assert any("Summary of earlier steps" in t for t in texts)


class TestM6ActionsToCompressEmpty:

    def test_compress_curr_true_but_all_actions_kept_no_llm(self):
        """keep_recent_steps >= len(action_steps), actions_to_compress=[], should not call LLM."""
        cm = make_cm(enabled=True, threshold=1, keep_recent_steps=10)
        curr_t = TaskStep(task="current_task")
        curr_a0 = ActionStep(step_number=0, model_output="output0 " + "Y" * 50, action_output="r0")
        curr_a1 = ActionStep(step_number=1, model_output="output1 " + "Y" * 50, action_output="r1")
        memory = AgentMemory(steps=[curr_t, curr_a0, curr_a1], system_prompt=None)
        original = make_original_messages(memory)

        model = make_model('{"task_overview": "summary"}')
        result = cm.compress_if_needed(model, memory, original, current_run_start_idx=0)

        model.assert_not_called()
        assert isinstance(result, list)
        assert "output0" in _joined(result)
        assert "output1" in _joined(result)


class TestM7CurrLLMReturnsNone:

    def test_curr_llm_returns_none_raw_curr_shown(self):
        """When _compress_current_with_cache returns None, curr_kept_steps=list(curr_steps), no crash."""
        cm = make_cm(enabled=True, threshold=1, keep_recent_steps=1)
        curr_t = TaskStep(task="current_task")
        curr_a0 = ActionStep(step_number=0, model_output="output0 " + "Y" * 50, action_output="r0")
        curr_a1 = ActionStep(step_number=1, model_output="output1 " + "Y" * 50, action_output="r1")
        memory = AgentMemory(steps=[curr_t, curr_a0, curr_a1], system_prompt=None)
        original = make_original_messages(memory)

        with patch.object(cm, '_compress_current_with_cache', return_value=None):
            model = make_model()
            result = cm.compress_if_needed(model, memory, original, current_run_start_idx=0)

        assert isinstance(result, list)
        assert "Summary of earlier steps" not in _joined(result)
        assert "output0" in _joined(result)
        assert "output1" in _joined(result)


class TestM8CurrCacheInMainPath:

    def test_compress_curr_false_with_valid_cache_applied_in_main_path(self):
        """
        Scenario: effective_tokens > threshold,
        prev_tokens > threshold*0.6 (compress_prev=True),
        curr_tokens <= threshold*0.4 (compress_curr=False),
        and curr cache valid -> elif branch applies curr cache.
        """
        cm = make_cm(enabled=True, threshold=100, keep_recent_pairs=1)

        t0, a0 = make_pair("prev0 " + "X" * 100, "pa0 " + "Y" * 100, 0)
        t1, a1 = make_pair("prev1 " + "X" * 100, "pa1 " + "Y" * 100, 1)
        curr_t = TaskStep(task="curr_task")
        curr_a = ActionStep(step_number=2, model_output="curr_out", action_output="curr_r")
        memory = AgentMemory(
            steps=[t0, a0, t1, a1, curr_t, curr_a],
            system_prompt=SystemPromptStep(system_prompt="sys"),
        )

        fp = ContextManager._action_fingerprint(curr_a)
        cm._current_summary_cache = CurrentSummaryCache("curr_cached_summary", 1, fp)

        def mock_effective_prev(steps):
            return 80

        def mock_effective_curr(steps):
            return 30

        with patch.object(cm, '_effective_prev_tokens', side_effect=mock_effective_prev):
            with patch.object(cm, '_effective_curr_tokens', side_effect=mock_effective_curr):
                model = make_model('{"task_overview": "prev_summary"}')
                original = make_original_messages(memory)
                result = cm.compress_if_needed(model, memory, original, current_run_start_idx=4)

        texts = _all_texts(result)
        assert any("curr_cached_summary" in t for t in texts)
        model.assert_called_once()
        assert "prev_summary" in _joined(result)


class TestM9OnlyCurrentNoCache:

    def test_only_current_run_over_threshold_triggers_curr_compression(self):
        """current_run_start_idx=0: all current-run, no prev, over threshold, no cache.
        Should compress curr and call LLM once.
        """
        cm = make_cm(enabled=True, threshold=1, keep_recent_steps=1)
        curr_t = TaskStep(task="current_task " + "X" * 50)
        actions = [
            ActionStep(step_number=i, model_output=f"output{i} " + "Y" * 50, action_output=f"r{i}")
            for i in range(3)
        ]
        memory = AgentMemory(steps=[curr_t] + actions, system_prompt=None)
        original = make_original_messages(memory)

        model = make_model('{"task_overview": "curr_summary"}')
        result = cm.compress_if_needed(model, memory, original, current_run_start_idx=0)

        assert result is not None
        assert isinstance(result, list)
        assert len(result) < len(original)
        model.assert_called_once()
        assert "Summary of earlier steps" in _joined(result)


class TestM10KeepRecentPairsBoundary:

    def test_keep_recent_pairs_larger_than_total_pairs_keeps_all(self):
        """keep_recent_pairs=999, pairs_to_compress=[], all pairs retained in raw form."""
        cm = make_cm(enabled=True, threshold=1, keep_recent_pairs=999)
        pairs = [make_pair(f"task{i} " + "X" * 20, f"action{i} " + "Y" * 20, i) for i in range(3)]
        steps = [s for t, a in pairs for s in (t, a)]
        memory = AgentMemory(steps=steps, system_prompt=None)
        original = make_original_messages(memory)

        model = make_model('{"task_overview": "summary"}')
        result = cm.compress_if_needed(model, memory, original, current_run_start_idx=6)

        model.assert_not_called()
        for i in range(3):
            assert f"task{i}" in _joined(result)


class TestM11BothLLMFail:

    def test_both_llm_calls_return_none_still_returns_list(self):
        """When both compression calls return None, result is still valid list, no exception."""
        cm = make_cm(enabled=True, threshold=1, keep_recent_pairs=1, keep_recent_steps=1)

        t0, a0 = make_pair("prev " + "X" * 50, "pa " + "Y" * 50, 0)
        t1, a1 = make_pair("prev1 " + "X" * 50, "pa1 " + "Y" * 50, 1)
        curr_t = TaskStep(task="curr_task " + "X" * 50)
        curr_a0 = ActionStep(step_number=2, model_output="cout0 " + "Y" * 50, action_output="r0")
        curr_a1 = ActionStep(step_number=3, model_output="cout1 " + "Y" * 50, action_output="r1")
        memory = AgentMemory(
            steps=[t0, a0, t1, a1, curr_t, curr_a0, curr_a1],
            system_prompt=SystemPromptStep(system_prompt="sys"),
        )
        original = make_original_messages(memory)

        with patch.object(cm, '_compress_previous_with_cache', return_value=None):
            with patch.object(cm, '_compress_current_with_cache', return_value=None):
                result = cm.compress_if_needed(None, memory, original, current_run_start_idx=4)

        assert isinstance(result, list)
        assert len(result) > 0


class TestM12NoSystemPrompt:

    def test_no_system_prompt_no_system_message_in_result(self):
        """memory.system_prompt=None, _build_messages should not produce system role message."""
        from stubs import _MessageRole
        cm = make_cm(enabled=True, threshold=1, keep_recent_pairs=1)
        t, a = make_pair("task " + "X" * 50, "action " + "Y" * 50, 0)
        t1, a1 = make_pair("task1 " + "X" * 50, "action1 " + "Y" * 50, 1)
        memory = AgentMemory(steps=[t, a, t1, a1], system_prompt=None)
        original = make_original_messages(memory)

        model = make_model('{"task_overview": "summary"}')
        result = cm.compress_if_needed(model, memory, original, current_run_start_idx=4)

        roles = [m.role for m in result]
        assert _MessageRole.SYSTEM not in roles


class TestM13StepLocalLogCleared:

    def test_step_local_log_cleared_at_start_of_each_compress_call(self):
        """Two consecutive compression calls, the second _step_local_log should not contain records from the first."""
        cm = make_cm(enabled=True, threshold=1, keep_recent_pairs=1)

        def _make_mem():
            t0, a0 = make_pair("task0 " + "X" * 50, "action0 " + "Y" * 50, 0)
            t1, a1 = make_pair("task1 " + "X" * 50, "action1 " + "Y" * 50, 1)
            return AgentMemory(steps=[t0, a0, t1, a1], system_prompt=None)

        model = make_model('{"task_overview": "summary"}')

        mem1 = _make_mem()
        cm.compress_if_needed(model, mem1, make_original_messages(mem1), current_run_start_idx=4)
        count_after_first = len(cm._step_local_log)
        assert count_after_first == 1
        assert cm._step_local_log[0].call_type == "previous_summary"

        mem2 = _make_mem()
        cm.compress_if_needed(model, mem2, make_original_messages(mem2), current_run_start_idx=4)
        count_after_second = len(cm._step_local_log)
        # reuse Previous_summary_cache; cache hit is still recorded in _step_local_log
        assert count_after_second == 1
        assert cm._step_local_log[0].call_type == "previous_cache_hit"