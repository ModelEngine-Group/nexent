from factories import make_cm, make_pair, make_model, make_memory_mixed, make_original_messages
from loader import AgentMemory, TaskStep, SystemPromptStep, CurrentSummaryCache, PreviousSummaryCache, ContextManager


def _all_texts(messages):
    return [
        b.get("text", "")
        for m in messages
        for b in (m.content if isinstance(m.content, list) else [])
        if isinstance(b, dict)
    ]
 
 
def _joined(messages):
    return " ".join(_all_texts(messages))
 
class TestCompressIfNeeded:

    def test_disabled_returns_original_messages(self):
        """config.enabled=False 时直接返回 original_messages，不做任何处理"""
        cm = make_cm(enabled=False, threshold=10)
        # prev: [T,A]; curr: [T,A]
        n_prev_pairs = 1
        n_curr_actions = 1
        memory = make_memory_mixed(n_prev_pairs,n_curr_actions)
        original = make_original_messages(memory)
        current_run_start_idx = 2 * n_prev_pairs  
        result = cm.compress_if_needed(None, memory, original, current_run_start_idx=current_run_start_idx)
        assert result is original

    def test_under_threshold_returns_original(self):
        """raw tokens < threshold 时直接返回，不调用 LLM"""
        cm = make_cm(enabled=True, threshold=999999)
        n_prev_pairs = 1
        n_curr_actions = 1
        memory = make_memory_mixed(n_prev_pairs,n_curr_actions)
        original = make_original_messages(memory)
        current_run_start_idx = 2 * n_prev_pairs 
        model = make_model()
        result = cm.compress_if_needed(None, memory, original, current_run_start_idx=current_run_start_idx)
        assert result is original
        model.assert_not_called()

    def test_over_threshold_triggers_compression(self):
        """raw tokens > threshold 时应调用 LLM（全 previous-run 场景）"""
        keep_recent_pairs = 1
        keep_recent_steps = 2
        cm = make_cm(enabled=True, threshold=10, keep_recent_steps=keep_recent_steps, keep_recent_pairs=keep_recent_pairs)
        n_prev_pairs = 3
        n_curr_actions = 2
        memory = make_memory_mixed(n_prev_pairs=n_prev_pairs, n_curr_actions=n_curr_actions)
        original = make_original_messages(memory)
        # system prompt + 2 * prev_pairs + curr_task + curr_actions
        assert len(original) == 1+ n_prev_pairs * 2 + 1 + n_curr_actions
        # current_run_start_idx = len(memory.steps) 表示全部为 previous-run，current-run 为空
        current_run_start_idx =  2 * n_prev_pairs
        model = make_model('{"task_overview": "摘要"}')
        result = cm.compress_if_needed(model, memory, original, current_run_start_idx)
        assert result is not None
        assert isinstance(result, list)
        # system prompt + prev_summary + 2 * keep_prev_pairs + curr_task + keep_curr_steps
        assert len(result) == 1 + 1 + 2 * keep_recent_pairs + 1 + keep_recent_steps
        model.assert_called_once()
        all_text = " ".join(
            b.get("text", "")
            for m in result for b in (m.content if isinstance(m.content, list) else [])
            if isinstance(b, dict)
        )
        # "Summary of ealier steps" in SummaryTaskStep
        assert "Summary of earlier steps" in all_text

    def test_run_boundary_clears_current_cache(self):
        """切换 run（current_run_start_idx 变化）时 且确保不触发 current summary的时候，current cache 应被清空"""
        cm = make_cm(enabled=True, threshold=1)
        # 预先设置 current cache
        cm._current_summary_cache = CurrentSummaryCache("旧缓存", 1, "fp")
        cm._last_run_start_idx = 5  # 上次的 idx
        memory = make_memory_mixed(1,0)
        original = make_original_messages(memory)
        model = make_model('{"task_overview": "摘要"}')
        # 用不同的 current_run_start_idx 调用 → 触发边界检测
        try:
            cm.compress_if_needed(model, memory, original, current_run_start_idx=0)
        except Exception:
            pass  # 这里只关心 cache 清零，不关心后续压缩是否成功
        assert cm._current_summary_cache is None

    def test_effective_tokens_shortcut_applies_cache(self):
        """effective tokens < threshold 时短路，直接应用已有 cache 构建消息（全 previous-run）"""
        cm = make_cm(enabled=True, threshold=10, keep_recent_pairs=0)
        # 两对 steps
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(2)]
        all_steps = []
        for t, a in pairs:
            all_steps.extend([t, a])
        all_steps.append(TaskStep(task="New Task"))
        memory = AgentMemory(steps=all_steps, system_prompt=SystemPromptStep(system_prompt="系统提示"))
        # 预设 prev cache（摘要非常短）
        last_t, last_a = pairs[1]
        fp = cm._pair_fingerprint(last_t.task, last_a.action_output)
        cm._previous_summary_cache = PreviousSummaryCache("短", 2, fp)

        model = make_model('{"task_overview": "摘要"}')
        original = make_original_messages(memory)
        # 全部为 previous-run
        current_run_start_idx = 2 * len(pairs)
        result = cm.compress_if_needed(model, memory, original, current_run_start_idx)
        # effective tokens 短路后 model 不应被调用（cache 直接应用）
        model.assert_not_called()
        assert isinstance(result, list)
        # system_prompt(1) + previous 摘要(1)，current task → 共 3 条消息
        assert len(result) == 3
        all_text = " ".join(
            b.get("text", "")
            for m in result for b in (m.content if isinstance(m.content, list) else [])
            if isinstance(b, dict)
        )
        assert "短" in all_text

    def test_current_run_cache_full_hit_no_llm_call(self):
        """current cache 完全命中时，current 部分应被摘要替代且不调用 LLM"""
        cm = make_cm(enabled=True, threshold=7)
        curr_t, curr_a = make_pair("curr_task", "curr_action", 0)
        # There is no previous pairs
        memory = AgentMemory(steps=[curr_t, curr_a], system_prompt=SystemPromptStep(system_prompt="系统提示"))

        fp = ContextManager._action_fingerprint(curr_a)
        # use very short summary, ensure effective tokens < raw tokens
        # end_steps in CurrentSummaryCache is the number of action steps, not including current task
        cm._current_summary_cache = CurrentSummaryCache("sum_cc", 1, fp)

        model = make_model()
        original = make_original_messages(memory)
        # current_run_start_idx=0 means there is no previous，only current-run
        result = cm.compress_if_needed(model, memory, original, current_run_start_idx=0)

        model.assert_not_called()
        assert isinstance(result, list)
        # system_prompt(1) + curr_task(1) + SummaryTaskStep(c)(1) → three messages
        assert len(result) == 3
        all_text = " ".join(
            b.get("text", "")
            for m in result for b in (m.content if isinstance(m.content, list) else [])
            if isinstance(b, dict)
        )
        assert "sum_cc" in all_text

    def test_both_caches_hit_result_structure(self):
        """prev and current cache hit in the meantime, result should include two summary"""
        cm = make_cm(enabled=True, threshold=30)

        prev_t, prev_a = make_pair(f"prev_task:{'X'*50}", f"prev_action: {'Y'*50}", 0)
        curr_t, curr_a = make_pair("curr_task", "curr_action", 1)
        memory = AgentMemory(
            steps=[prev_t, prev_a, curr_t, curr_a],
            system_prompt=SystemPromptStep(system_prompt="系统提示"),
        )

        # should trigger compression
        assert cm._estimate_tokens(memory) > cm.config.token_threshold
        # prev cache covers previous runs
        prev_fp = cm._pair_fingerprint(prev_t.task, prev_a.action_output)
        cm._previous_summary_cache = PreviousSummaryCache("prev_sum", 1, prev_fp)

        # current cache covers current action
        curr_fp = ContextManager._action_fingerprint(curr_a)
        cm._current_summary_cache = CurrentSummaryCache("curr_sum", 1, curr_fp)

        model = make_model()
        original = make_original_messages(memory)
        # the first two steps are previous-run，the last two steps are current-run
        current_run_start_idx = 2

        result = cm.compress_if_needed(model, memory, original, current_run_start_idx)

        model.assert_not_called()
        assert isinstance(result, list)
        # system(1) + prev_summary(1) + curr_task(1) + curr_summary(1) = four messages
        assert len(result) == 4
        texts = [
            b.get("text", "")
            for m in result for b in (m.content if isinstance(m.content, list) else [])
            if isinstance(b, dict)
        ]
        assert any("prev_sum" in t for t in texts)
        assert any("curr_sum" in t for t in texts)
        assert cm._msg_token_count(result) < cm.config.token_threshold

    def test_mixed_prev_and_curr_over_threshold(self):
        """previous + current 同时存在且都超阈值时，应分别触发压缩"""
        cm = make_cm(enabled=True, threshold=1, keep_recent_pairs=1, keep_recent_steps=1)
        # previous: 3 对(6 steps)  +  current: task + 3 actions(4 steps)
        memory = make_memory_mixed(n_prev_pairs=3, n_curr_actions=3)
        original = make_original_messages(memory)

        # 前 6 个 step 属于 previous-run，后 4 个属于 current-run
        current_run_start_idx = 6
        model = make_model('{"task_overview": "摘要"}')
        result = cm.compress_if_needed(model, memory, original, current_run_start_idx)

        assert result is not None
        assert cm._previous_summary_cache is not None
        assert cm._current_summary_cache is not None 
        assert isinstance(result, list)
        assert len(result) < len(original)
        # prev 和 curr 都会触发压缩，因此 model 至少被调用两次
        assert model.call_count >= 2
        all_text = " ".join(
            b.get("text", "")
            for m in result for b in (m.content if isinstance(m.content, list) else [])
            if isinstance(b, dict)
        )
        assert "Summary of earlier steps" in all_text


