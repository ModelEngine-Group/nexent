 
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
 
from unittest.mock import MagicMock, patch
 
from factories import make_cm, make_pair, make_model
from loader import (
    ActionStep,
    ContextManager,
    CurrentSummaryCache,
    PreviousSummaryCache,
    TaskStep,
)
 
 
# ──────────────────────────────────────────────────────────────
# 工具
# ──────────────────────────────────────────────────────────────
 
def _llm_text(model) -> str:
    """从 mock model 的最后一次调用中提取拼接后的 user prompt 文本。"""
    call_args = model.call_args[0][0]
    return " ".join(
        b.get("text", "")
        for m in call_args
        for b in (m.content if isinstance(m.content, list) else [])
        if isinstance(b, dict)
    )
 
def _all_texts(messages):
    return [
        b.get("text", "")
        for m in messages
        for b in (m.content if isinstance(m.content, list) else [])
        if isinstance(b, dict)
    ]
 
 
def _joined(messages):
    return " ".join(_all_texts(messages))
 
 
# ══════════════════════════════════════════════════════════════
# P 系列：_compress_previous_with_cache 补充
# ══════════════════════════════════════════════════════════════
 
class TestCompressPreviousExtra:
 
    # ── P1：full hit covered_pairs 对齐但 fp 不匹配 → 直接走 fresh ──
 
    def test_P1_full_hit_fp_mismatch_goes_to_fresh(self):
        """covered_pairs == len(pairs) 但 fingerprint 错误。
        不应走增量路径（covered < len 的条件不满足），
        直接进入 fresh 全量压缩。
        """
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(2)]
        # covered_pairs 对齐，但 fingerprint 故意错误
        cm._previous_summary_cache = PreviousSummaryCache(
            summary_text="旧摘要", covered_pairs=2, anchor_fingerprint="WRONG"
        )
        model = make_model('{"task_overview": "fresh摘要"}')
        result = cm._compress_previous_with_cache(pairs, model)
 
        assert result is not None
        model.assert_called_once()
        # fresh 路径的 prompt 中不应包含旧摘要（无增量前缀）
        assert "旧摘要" not in _llm_text(model)
        # cache 应被 fresh 结果覆盖
        assert cm._previous_summary_cache.covered_pairs == 2

    # ── P2：增量路径 input_tokens 超预算 → fall-through 到 fresh ──
 
    def test_P2_incremental_over_budget_falls_through_to_fresh(self):
        """增量输入 token 数超过 max_summary_input_tokens，
        应跳过增量直接走 fresh，仍调用 LLM 一次（fresh）。
        """
        cm = make_cm()
        # 把预算压到 0，让所有增量输入都超预算
        cm.config.max_summary_input_tokens = 0
 
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(3)]
        anchor_t, anchor_a = pairs[1]
        fp = cm._pair_fingerprint(anchor_t.task, anchor_a.action_output)
        cm._previous_summary_cache = PreviousSummaryCache("旧摘要", 2, fp)
 
        model = make_model('{"task_overview": "fresh摘要"}')
        # import pdb; pdb.set_trace()

        result = cm._compress_previous_with_cache(pairs, model)
        assert result is not None
        model.assert_called_once()
        # fresh 路径不含旧摘要的增量前缀
        assert "旧摘要" not in _llm_text(model)
        # max_summary_input_tokens 为 0， 会走入 fresh路径中的 summarize_pairs
        # 且 会进入 L2 trim，由于 max_summary_input_tokens 为 0，几乎会完全 trim，到仍然会保留最后一个pair
        # 所以会有
        assert "task2" in _llm_text(model)
        assert "fresh" in result 
        
    # ── P3：增量 LLM 返回 None → fall-through 到 fresh ──
 
    def test_P3_incremental_llm_none_falls_through_to_fresh(self):
        """_generate_summary 在增量路径返回 None 时，
        代码 fall-through 到 fresh，最终应再调用一次 LLM。
        """
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(3)]
        anchor_t, anchor_a = pairs[1]
        fp = cm._pair_fingerprint(anchor_t.task, anchor_a.action_output)
        cm._previous_summary_cache = PreviousSummaryCache("旧摘要", 2, fp)
 
        call_count = [0]
        def side_effect(text, model_, call_type="summary"):
            call_count[0] += 1
            if call_count[0] == 1:
                return None          # 增量调用失败
            return '{"task_overview": "fresh摘要"}'  # fresh 调用成功
 
        with patch.object(cm, '_generate_summary', side_effect=side_effect):
            result = cm._compress_previous_with_cache(pairs, MagicMock())
 
        assert call_count[0] == 2    # 增量 + fresh 各一次
        assert result is not None


    # ── P4：fresh LLM 返回 None → return None，旧 cache 不被清除 ──
 
    def test_P4_fresh_llm_none_returns_none_and_preserves_old_cache(self):
        """_summarize_pairs 返回 (None, False) 时：
        - 函数返回 None
        - 既有的 _previous_summary_cache 不被修改
        """
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(2)]
        # 预设一个旧 cache（与当前 pairs 不匹配，走 fresh 路径）
        cm._previous_summary_cache = PreviousSummaryCache("旧摘要", 99, "bad_fp")
 
        with patch.object(cm, '_summarize_pairs', return_value=(None, False)):
            result = cm._compress_previous_with_cache(pairs, MagicMock())
 
        assert result is None
        # 旧 cache 不应被覆盖（neither 分支都需要 summary_text 为真值）
        assert cm._previous_summary_cache.summary_text == "旧摘要"


    def test_P4_fresh_llm_none_no_cache_remains_none(self):
        """初始无 cache 时，fresh LLM 返回 None → cache 仍为 None。"""
        cm = make_cm()
        pairs = [make_pair("task", "action", 0)]
        assert cm._previous_summary_cache is None
 
        with patch.object(cm, '_summarize_pairs', return_value=(None, False)):
            result = cm._compress_previous_with_cache(pairs, MagicMock())
 
        assert result is None
        assert cm._previous_summary_cache is None


# ══════════════════════════════════════════════════════════════
# C 系列：_compress_current_with_cache 补充
# ══════════════════════════════════════════════════════════════
 
class TestCompressCurrentExtra:
 
    def _make_actions(self, n):
        return [
            ActionStep(step_number=i, model_output=f"output{i}", action_output=f"result{i}")
            for i in range(n)
        ]
 
    # ── C1：full hit end_steps 对齐但 fp 不匹配 → 直接走 fresh ──
 
    def test_C1_full_hit_fp_mismatch_goes_to_fresh(self):
        """end_steps == len(actions) 但 anchor_fingerprint 错误。
        增量条件 0 < end_steps < len 不满足，直接走 fresh。
        """
        cm = make_cm()
        actions = self._make_actions(2)
        cm._current_summary_cache = CurrentSummaryCache(
            summary_text="旧摘要", end_steps=2, anchor_fingerprint="WRONG"
        )
        model = make_model('{"task_overview": "fresh摘要"}')
        result = cm._compress_current_with_cache(TaskStep(task="t"), actions, model)
 
        assert result is not None
        assert "fresh摘要" in result 
        assert "旧摘要" not in result
        model.assert_called_once()
        # cache 被 fresh 结果覆盖，fingerprint 更新为真实值
        real_fp = ContextManager._action_fingerprint(actions[-1])
        assert cm._current_summary_cache.anchor_fingerprint == real_fp


    # ── C2：增量 anchor action fp 不匹配 → 走 fresh ──
 
    def test_C2_incremental_anchor_fp_mismatch_goes_to_fresh(self):
        """cache.end_steps < len(actions)（满足增量条件），
        但 anchor action 的 fingerprint 与 cache 不符 → fall-through 到 fresh。
        """
        cm = make_cm()
        actions = self._make_actions(3)
        # end_steps=2（< 3），但 fingerprint 故意错误
        cm._current_summary_cache = CurrentSummaryCache(
            summary_text="旧摘要", end_steps=2, anchor_fingerprint="WRONG"
        )
        model = make_model('{"task_overview": "fresh摘要"}')
        result = cm._compress_current_with_cache(TaskStep(task="t"), actions, model)
 
        assert result is not None
        model.assert_called_once()
        # fresh 路径 prompt 不含旧摘要增量前缀
        assert "旧摘要" not in _llm_text(model)
        assert "fresh摘要" in  result

    # ── C4：增量 LLM 返回 None → fall-through 到 fresh ──
 
    def test_C4_incremental_llm_none_falls_through_to_fresh(self):
        cm = make_cm()
        actions = self._make_actions(3)
        fp = ContextManager._action_fingerprint(actions[1])
        cm._current_summary_cache = CurrentSummaryCache("旧摘要", 2, fp)
 
        call_count = [0]
        def side_effect(text, model_, call_type="summary"):
            call_count[0] += 1
            if call_count[0] == 1:
                return None
            return '{"task_overview": "fresh摘要"}'
 
        with patch.object(cm, '_generate_summary', side_effect=side_effect):
            result = cm._compress_current_with_cache(TaskStep(task="t"), actions, MagicMock())
 
        assert call_count[0] == 2
        assert result is not None
        # fresh 路径写入了新 cache，end_steps 为原始 len
        assert cm._current_summary_cache.end_steps == len(actions)


  # ── C5：fresh actions 被 trim（is_full_coverage=False）──
 
    def test_C5_fresh_actions_trimmed_cache_uses_original_len(self):
        """_trim_actions_to_budget 裁掉了部分 action，
        但 end_steps 仍应记录原始 len(actions_to_compress)，
        确保下次调用时 cache 能覆盖相同的范围。
        """
        cm = make_cm()
        actions = self._make_actions(4)
 
        # 让 _trim_actions_to_budget 只保留最后 1 个
        with patch.object(cm, '_trim_actions_to_budget', return_value=[actions[-1]]):
            model = make_model('{"task_overview": "trimmed摘要"}')
            result = cm._compress_current_with_cache(TaskStep(task="t"), actions, model)
 
        assert result is not None
        # end_steps 应为原始 len=4，而非 trim 后的 1
        assert cm._current_summary_cache.end_steps == 4
        # anchor_fingerprint 应为原始最后一个 action 的 fingerprint
        real_fp = ContextManager._action_fingerprint(actions[-1])
        assert cm._current_summary_cache.anchor_fingerprint == real_fp

    def test_C5_fresh_partial_trim_still_calls_llm_once(self):
        """trim 发生后仍只调用一次 LLM（不重试）。"""
        cm = make_cm()
        actions = self._make_actions(3)
 
        with patch.object(cm, '_trim_actions_to_budget', return_value=[actions[-1]]):
            model = make_model('{"task_overview": "摘要"}')
            cm._compress_current_with_cache(TaskStep(task="t"), actions, model)
 
        model.assert_called_once()


    # ── C6：fresh LLM 返回 None → cache 写入 None，return None ──
 
    def test_C6_fresh_llm_none_writes_none_to_cache(self):
        """current 的 fresh 路径如果LLM call失败，则不会有 cache
        此时，只进行截断
        """
        cm = make_cm()
        actions = self._make_actions(2)
 
        with patch.object(cm, '_generate_summary', return_value=None):
            result = cm._compress_current_with_cache(TaskStep(task="t"), actions, MagicMock())
 
        assert "Truncated" in result
        assert cm._current_summary_cache is None



    def test_C6_vs_previous_asymmetry(self):
        """回归测试：明确 previous 和 current 在 LLM=None 时行为的非对称性。
        previous fresh=None → cache 不写入（保留旧值）
        current  fresh=None → cache 不写入
        """
        cm = make_cm()
        pairs = [make_pair("task", "action", 0)]
        actions = [ActionStep(step_number=0, model_output="out", action_output="r")]
 
        old_prev_cache = PreviousSummaryCache("旧prev", 99, "bad")
        cm._previous_summary_cache = old_prev_cache
 
        with patch.object(cm, '_summarize_pairs', return_value=(None, False)):
            cm._compress_previous_with_cache(pairs, MagicMock())
        # previous：旧 cache 保留
        assert cm._previous_summary_cache is old_prev_cache
 
        with patch.object(cm, '_generate_summary', return_value=None):
            cm._compress_current_with_cache(TaskStep(task="t"), actions, MagicMock())
        # current：若generate summary失败，则_current_summary_cache保持原样，就该测试而言，则为None
        assert cm._current_summary_cache is  None
