"""
unit/test_compress_if_needed_extra.py
──────────────────────────────────────
补充 TestCompressIfNeeded 中缺失的分支覆盖。
 
原有测试已覆盖：
  G1 disabled / under-threshold / run-boundary / G2 both-cache / G2 prev-only /
  G2 curr-only / main-path prev+curr both compress / main-path mixed
 
本文件补充（对应分支图中 M1-M13）：
  M1  首次调用 _last_run_start_idx=None → 不抛异常、不清缓存
  M2  G2 shortcut 无 cache 时返回原始 raw messages（不调 LLM）
  M3  compress_prev=True 但 pairs_to_compress 为空（keep_n ≥ 所有 pair）
  M4  compress_prev=True，LLM 返回 None → 原始 prev 照常展示，不崩溃
  M5  compress_prev=False 且 prev cache 有效 → 主路径稳定期应用 cache（非 G2）
  M6  compress_curr=True 但 actions_to_compress 为空
  M7  compress_curr=True，LLM 返回 None → 原始 curr 照常展示，不崩溃
  M8  compress_curr=False 且 curr cache 有效 → 主路径稳定期应用 cache（非 G2）
  M9  仅 current-run（current_run_start_idx=0），无 previous，超阈值，无 cache
  M10 keep_recent_pairs 超过 pairs 总数时边界处理
  M11 prev+curr 两次 LLM 都失败 → 返回值仍是 list 不崩溃
  M12 无 system_prompt 时结果中无 system 消息
  M13 每次 compress 调用都清空 _step_local_log
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
 
 
# ──────────────────────────────────────────────────────────────
# 工具：从消息列表提取所有文本块
# ──────────────────────────────────────────────────────────────
 
def _all_texts(messages):
    return [
        b.get("text", "")
        for m in messages
        for b in (m.content if isinstance(m.content, list) else [])
        if isinstance(b, dict)
    ]
 
 
def _joined(messages):
    return " ".join(_all_texts(messages))
 
 
# ──────────────────────────────────────────────────────────────
# M1  首次调用 _last_run_start_idx=None → 无异常、无清缓存
# ──────────────────────────────────────────────────────────────
 
class TestM1FirstCall:
 
    def test_first_call_no_exception_and_no_cache_clear(self):
        """初始状态 _last_run_start_idx=None，首次调用不应清空 current cache。"""
        cm = make_cm(enabled=True, threshold=999999)  # 高阈值，直接走 G1 under-threshold
        cm._current_summary_cache = CurrentSummaryCache("已有摘要", 1, "fp")
        assert cm._last_run_start_idx is None
 
        t, a = make_pair("task", "action", 0)
        memory = AgentMemory(steps=[t, a], system_prompt=None)
        original = make_original_messages(memory)
 
        result = cm.compress_if_needed(None, memory, original, current_run_start_idx=2)
 
        # G1 短路直接返回，current cache 不应被清空
        assert result is original
        assert cm._current_summary_cache is not None
# ──────────────────────────────────────────────────────────────
# M2  G2 shortcut 无 cache：effective ≤ threshold，但无任何有效 cache
# ──────────────────────────────────────────────────────────────
 
class TestM2G2NoCacheRawReturn:
 
    def test_g2_shortcut_no_cache_returns_raw_messages(self):
        """effective ≤ threshold 但没有任何 cache，应直接用 _build_messages 组装原始步骤。"""
        cm = make_cm(enabled=True, threshold=10)
        # 非常短的内容，effective tokens 必然 ≤ 10
        t, a = make_pair("x", "y", 0)
        memory = AgentMemory(steps=[t, a], system_prompt=None)
        original = make_original_messages(memory)

        # 确保 _estimate_tokens > threshold（触发进入函数体），但 _effective_tokens ≤ threshold
        with patch.object(cm, '_estimate_tokens', return_value=50):
            with patch.object(cm, '_effective_tokens', return_value=5):
                model = make_model()
                result = cm.compress_if_needed(model, memory, original, current_run_start_idx=2)
 
        model.assert_not_called()
        assert isinstance(result, list)
        # 无摘要：结果中不含 "Summary of earlier steps"
        assert "Summary of earlier steps" not in _joined(result)
        # 原始步骤内容仍然出现
        assert "x" in _joined(result)

# ──────────────────────────────────────────────────────────────
# M3  compress_prev=True 但 pairs_to_compress 为空（keep_n ≥ 所有 pair）
# ──────────────────────────────────────────────────────────────
 
class TestM3PairsToCompressEmpty:
 
    def test_compress_prev_true_but_all_pairs_kept_no_llm(self):
        """keep_recent_pairs ≥ len(pairs)，pairs_to_compress=[]，不应调用 LLM。
        结果中前 pair 全部保留（以 raw 形式）。
        """
        # keep_recent_pairs=10 远大于实际 pair 数 2
        cm = make_cm(enabled=True, threshold=1, keep_recent_pairs=10)
        t0, a0 = make_pair("task0 " + "X" * 50, "action0 " + "Y" * 50, 0)
        t1, a1 = make_pair("task1 " + "X" * 50, "action1 " + "Y" * 50, 1)
        memory = AgentMemory(steps=[t0, a0, t1, a1], system_prompt=None)
        original = make_original_messages(memory)
 
        model = make_model('{"task_overview": "摘要"}')
        # 全部为 previous-run
        result = cm.compress_if_needed(model, memory, original, current_run_start_idx=4)

        model.assert_not_called()
        assert isinstance(result, list)
        # 两个 task 的内容都应出现
        assert "task0" in _joined(result)
        assert "task1" in _joined(result)

# ──────────────────────────────────────────────────────────────
# M4  compress_prev=True，LLM 返回 None → graceful degradation
# ──────────────────────────────────────────────────────────────
 
class TestM4PrevLLMReturnsNone:
 
    def test_prev_llm_returns_none_raw_steps_shown(self):
        """_compress_previous_with_cache 返回 None 时，prev_summary_step=None，
        原始 prev steps 照常出现在结果中，不崩溃。
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
        # 无摘要步骤
        assert "Summary of earlier steps" not in _joined(result)
        # keep_recent_pairs=1：pairs_to_keep=[pair1]，pair0 被 compress 但 LLM 返回 None 所以 prev_summary_step=None
        # 实际结果应包含 task1 的内容
        assert "task1" in _joined(result)


 
# ──────────────────────────────────────────────────────────────
# M5  compress_prev=False 且 prev cache 有效 → 主路径稳定期应用 cache
# ──────────────────────────────────────────────────────────────
 
class TestM5PrevCacheInMainPath:
 
    def test_compress_prev_false_with_valid_cache_applied_in_main_path(self):
        """
        场景：effective_tokens > threshold（进入主路径），
        但 prev_tokens ≤ threshold*0.6（compress_prev=False），
        且 prev cache 有效 → 走 elif 分支应用 prev cache。
        这与 G2 shortcut 不同：G2 是 effective ≤ threshold 时短路。
        """
        cm = make_cm(enabled=True, threshold=100, keep_recent_pairs=1)

        # 确保这里示例的prev 其长度要明显大于下面构建的previous_summary_cache的内容长度
        t, a = make_pair("prev_task" + "X" * 200, "prev_action" + "Y" * 200, 0)
        curr_t, curr_a = make_pair("curr_task " + "X" * 200, "curr_action " + "Y" * 200, 1)
        memory = AgentMemory(
            steps=[t, a, curr_t, curr_a],
            system_prompt=SystemPromptStep(system_prompt="sys"),
        )
 
        fp = cm._pair_fingerprint(t.task, a.action_output)
        cm._previous_summary_cache = PreviousSummaryCache("prev_cached_summary", 1, fp)

        # 控制 token 分布：prev 很小（不触发 compress_prev），curr 很大（触发 compress_curr）
        # effective total > threshold（G2 不短路），prev ≤ 60（compress_prev=False）
        def mock_effective_prev(steps):
            return 40  # ≤ 60 = 100*0.6
 
        def mock_effective_curr(steps):
            return 80  # > 40 = 100*0.4，触发 compress_curr
 
        with patch.object(cm, '_effective_prev_tokens', side_effect=mock_effective_prev):
            with patch.object(cm, '_effective_curr_tokens', side_effect=mock_effective_curr):
                # effective_tokens = sys(~2) + 40 + 80 = ~122 > 100，G2 不触发
                model = make_model('{"task_overview": "curr_summary"}')
                original = make_original_messages(memory)
                result = cm.compress_if_needed(model, memory, original, current_run_start_idx=2)
        texts = _all_texts(result)
        # prev cache 应被应用：出现摘要内容
        assert any("prev_cached_summary" in t for t in texts)
        # curr 被压缩：出现 Summary of earlier steps
        assert any("Summary of earlier steps" in t for t in texts)
 
 
# ──────────────────────────────────────────────────────────────
# M6  compress_curr=True 但 actions_to_compress 为空
# ──────────────────────────────────────────────────────────────
 
class TestM6ActionsToCompressEmpty:
 
    def test_compress_curr_true_but_all_actions_kept_no_llm(self):
        """keep_recent_steps ≥ len(action_steps)，actions_to_compress=[]，不应调用 LLM。"""
        cm = make_cm(enabled=True, threshold=1, keep_recent_steps=10)
        curr_t = TaskStep(task="current_task")
        curr_a0 = ActionStep(step_number=0, model_output="output0 " + "Y" * 50, action_output="r0")
        curr_a1 = ActionStep(step_number=1, model_output="output1 " + "Y" * 50, action_output="r1")
        memory = AgentMemory(steps=[curr_t, curr_a0, curr_a1], system_prompt=None)
        original = make_original_messages(memory)
 
        model = make_model('{"task_overview": "摘要"}')
        # current_run_start_idx=0：全部为 current-run
        result = cm.compress_if_needed(model, memory, original, current_run_start_idx=0)
 
        model.assert_not_called()
        assert isinstance(result, list)
        assert "output0" in _joined(result)
        assert "output1" in _joined(result)

# ──────────────────────────────────────────────────────────────
# M7  compress_curr=True，LLM 返回 None → graceful degradation
# ──────────────────────────────────────────────────────────────
 
class TestM7CurrLLMReturnsNone:
 
    def test_curr_llm_returns_none_raw_curr_shown(self):
        """_compress_current_with_cache 返回 None 时，curr_kept_steps=list(curr_steps)，不崩溃。"""
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
        # 无摘要，原始 curr steps 直接展示
        assert "Summary of earlier steps" not in _joined(result)
        assert "output0" in _joined(result)
        assert "output1" in _joined(result)


# ──────────────────────────────────────────────────────────────
# M8  compress_curr=False 且 curr cache 有效 → 主路径稳定期应用 cache
# ──────────────────────────────────────────────────────────────
 
class TestM8CurrCacheInMainPath:
 
    def test_compress_curr_false_with_valid_cache_applied_in_main_path(self):
        """
        场景：effective_tokens > threshold，
        prev_tokens > threshold*0.6（compress_prev=True），
        curr_tokens ≤ threshold*0.4（compress_curr=False），
        且 curr cache 有效 → 走 elif 分支应用 curr cache。
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
            return 80  # > 60 = 100*0.6 → compress_prev=True
 
        def mock_effective_curr(steps):
            return 30  # ≤ 40 = 100*0.4 → compress_curr=False
 
        with patch.object(cm, '_effective_prev_tokens', side_effect=mock_effective_prev):
            with patch.object(cm, '_effective_curr_tokens', side_effect=mock_effective_curr):
                model = make_model('{"task_overview": "prev_summary"}')
                original = make_original_messages(memory)
                result = cm.compress_if_needed(model, memory, original, current_run_start_idx=4)
 
        texts = _all_texts(result)
        # curr cache 应被应用
        assert any("curr_cached_summary" in t for t in texts)
        # prev 被 LLM 压缩
        model.assert_called_once()
        assert "prev_summary" in _joined(result)


# ──────────────────────────────────────────────────────────────
# M9  仅 current-run，无 previous，超阈值，无 cache
# ──────────────────────────────────────────────────────────────
 
class TestM9OnlyCurrentNoCache:
 
    def test_only_current_run_over_threshold_triggers_curr_compression(self):
        """current_run_start_idx=0：全部为 current-run，无 prev，超阈值，无 cache。
        应仅压缩 curr 并调用 LLM 一次。
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


# ──────────────────────────────────────────────────────────────
# M10 keep_recent_pairs 边界：超过实际 pair 数时等价于不丢弃任何 pair
# ──────────────────────────────────────────────────────────────
 
class TestM10KeepRecentPairsBoundary:
 
    def test_keep_recent_pairs_larger_than_total_pairs_keeps_all(self):
        """keep_recent_pairs=999 时，pairs_to_compress=[]，所有 pair 原样保留。"""
        cm = make_cm(enabled=True, threshold=1, keep_recent_pairs=999)
        pairs = [make_pair(f"task{i} " + "X" * 20, f"action{i} " + "Y" * 20, i) for i in range(3)]
        steps = [s for t, a in pairs for s in (t, a)]
        memory = AgentMemory(steps=steps, system_prompt=None)
        original = make_original_messages(memory)
 
        model = make_model('{"task_overview": "摘要"}')
        result = cm.compress_if_needed(model, memory, original, current_run_start_idx=6)
 
        model.assert_not_called()
        for i in range(3):
            assert f"task{i}" in _joined(result)



# ──────────────────────────────────────────────────────────────
# M11 prev+curr 两次 LLM 都失败 → 返回值仍是 list 不崩溃
# ──────────────────────────────────────────────────────────────
 
class TestM11BothLLMFail:
 
    def test_both_llm_calls_return_none_still_returns_list(self):
        """两次压缩调用都返回 None 时，结果仍是合法的 list，不抛异常。"""
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
 
 # ──────────────────────────────────────────────────────────────
# M12 无 system_prompt 时结果中无 system 消息
# ──────────────────────────────────────────────────────────────
 
class TestM12NoSystemPrompt:
 
    def test_no_system_prompt_no_system_message_in_result(self):
        """memory.system_prompt=None 时，_build_messages 不应产生 system role 消息。"""
        from stubs import _MessageRole
        cm = make_cm(enabled=True, threshold=1, keep_recent_pairs=1)
        t, a = make_pair("task " + "X" * 50, "action " + "Y" * 50, 0)
        t1, a1 = make_pair("task1 " + "X" * 50, "action1 " + "Y" * 50, 1)
        memory = AgentMemory(steps=[t, a, t1, a1], system_prompt=None)
        original = make_original_messages(memory)
 
        model = make_model('{"task_overview": "摘要"}')
        result = cm.compress_if_needed(model, memory, original, current_run_start_idx=4)
 
        roles = [m.role for m in result]
        assert _MessageRole.SYSTEM not in roles



# ──────────────────────────────────────────────────────────────
# M13 每次 compress 调用都清空 _step_local_log（不跨 step 累积）
# ──────────────────────────────────────────────────────────────
 
class TestM13StepLocalLogCleared:
 
    def test_step_local_log_cleared_at_start_of_each_compress_call(self):
        """连续两次压缩调用，第二次的 _step_local_log 不应包含第一次的记录。"""
        cm = make_cm(enabled=True, threshold=1, keep_recent_pairs=1)
 
        def _make_mem():
            t0, a0 = make_pair("task0 " + "X" * 50, "action0 " + "Y" * 50, 0)
            t1, a1 = make_pair("task1 " + "X" * 50, "action1 " + "Y" * 50, 1)
            return AgentMemory(steps=[t0, a0, t1, a1], system_prompt=None)
 
        model = make_model('{"task_overview": "摘要"}')
 
        mem1 = _make_mem()
        cm.compress_if_needed(model, mem1, make_original_messages(mem1), current_run_start_idx=4)
        count_after_first = len(cm._step_local_log)

        mem2 = _make_mem()
        cm.compress_if_needed(model, mem2, make_original_messages(mem2), current_run_start_idx=4)
        count_after_second = len(cm._step_local_log)
        assert count_after_first == 1
        # reuse Previous_summary_cache, no compressioin
        assert count_after_second == 0