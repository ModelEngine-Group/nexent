from factories import make_cm, make_pair, make_model
from loader import ActionStep, PreviousSummaryCache, ContextManager, CurrentSummaryCache, TaskStep

class TestCompressPreviousWithCache:

    def _make_pairs_with_cache(self, n=2):
        """生成 n 个 pair，并预设完整 cache 命中"""
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(n)]
        last_t, last_a = pairs[-1]
        fp = cm._pair_fingerprint(last_t.task, last_a.action_output)
        cm._previous_summary_cache = PreviousSummaryCache(
            summary_text="已有摘要", covered_pairs=n, anchor_fingerprint=fp
        )
        return cm, pairs

    # 路径一：完整 cache 命中
    def test_previous_full_cache_hit_no_llm_call(self):
        cm, pairs = self._make_pairs_with_cache(n=2)
        model = make_model()
        result = cm._compress_previous_with_cache(pairs, model)
        assert result == "已有摘要"
        model.assert_not_called()  # 不应调用 LLM

    # 路径二：增量压缩
    def test_previous_incremental_calls_llm_with_old_summary(self):
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(3)]
        # cache 只覆盖前2对
        anchor_t, anchor_a = pairs[1]
        fp = cm._pair_fingerprint(anchor_t.task, anchor_a.action_output)
        cm._previous_summary_cache = PreviousSummaryCache(
            summary_text="旧摘要", covered_pairs=2, anchor_fingerprint=fp
        )
        model = make_model('{"task_overview": "增量摘要"}')
        result = cm._compress_previous_with_cache(pairs, model)
        assert result is not None
        model.assert_called_once()
        # 调用参数应包含旧摘要
        call_args = model.call_args[0][0]  # messages list
        full_text = " ".join(
            b.get("text", "") for m in call_args for b in (m.content if isinstance(m.content, list) else [])
        )
        assert "旧摘要" in full_text

    # 路径三：fresh 全量压缩
    def test_previous_fresh_compress_writes_cache(self):
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(2)]
        model = make_model('{"task_overview": "全量摘要"}')
        result = cm._compress_previous_with_cache(pairs, model)
        assert result is not None
        assert cm._previous_summary_cache is not None
        assert cm._previous_summary_cache.covered_pairs == 2

    # 增量命中后缓存被正确更新
    def test_previous_incremental_updates_cache_to_full_coverage(self):
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(3)]
        anchor_t, anchor_a = pairs[1]
        fp = cm._pair_fingerprint(anchor_t.task, anchor_a.action_output)
        cm._previous_summary_cache = PreviousSummaryCache("旧摘要", 2, fp)
        model = make_model('{"task_overview": "新摘要"}')
        cm._compress_previous_with_cache(pairs, model)
        assert cm._previous_summary_cache.covered_pairs == 3
        assert "新摘要" in cm._previous_summary_cache.summary_text

    # fingerprint 不匹配 → 不走增量，走 fresh
    def test_previous_fingerprint_mismatch_falls_through_to_fresh(self):
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(3)]
        # 故意放错 fingerprint
        cm._previous_summary_cache = PreviousSummaryCache("旧摘要", 2, "wrong_fp")
        model = make_model('{"task_overview": "fresh摘要"}')
        result = cm._compress_previous_with_cache(pairs, model)
        assert result is not None
        call_args = model.call_args[0][0]
        full_text = " ".join(
            b.get("text", "") for m in call_args for b in (m.content if isinstance(m.content, list) else [])
        )
        # import pdb; pdb.set_trace()
        # fresh 路径不应包含旧摘要
        assert "旧摘要" not in full_text
        # 此时应该走入 fresh 更新, coverd_pairs也将更新
        assert cm._previous_summary_cache.covered_pairs == 3


    # 空 pairs 返回 None
    def test_previous_empty_pairs_returns_none(self):
        cm = make_cm()
        model = make_model()
        assert cm._compress_previous_with_cache([], model) is None
        model.assert_not_called()


# ============================================================
# 5. Current 压缩路径三条分支
# ============================================================

class TestCompressCurrentWithCache:

    def _make_actions_with_cache(self, n=2):
        cm = make_cm()
        actions = [ActionStep(step_number=i, model_output=f"output{i}", action_output=f"result{i}") for i in range(n)]
        fp = ContextManager._action_fingerprint(actions[-1])
        cm._current_summary_cache = CurrentSummaryCache("已有步骤摘要", n, fp)
        return cm, actions

    # 路径一：完整 cache 命中
    def test_current_full_cache_hit_no_llm_call(self):
        cm, actions = self._make_actions_with_cache(n=2)
        model = make_model()
        task = TaskStep(task="当前任务")
        result = cm._compress_current_with_cache(task, actions, model)
        assert result == "已有步骤摘要"
        model.assert_not_called()

    # 路径二：增量
    def test_current_incremental_calls_llm(self):
        cm = make_cm()
        actions = [ActionStep(step_number=i, model_output=f"output{i}", action_output=f"result{i}") for i in range(3)]
        fp = ContextManager._action_fingerprint(actions[1])
        cm._current_summary_cache = CurrentSummaryCache("旧步骤摘要", 2, fp)
        model = make_model('{"task_overview": "增量步骤摘要"}')
        task = TaskStep(task="任务")
        result = cm._compress_current_with_cache(task, actions, model)
        assert "增量步骤" in result 
        assert "旧步骤" not in result 
        assert cm._current_summary_cache.end_steps == 3
        model.assert_called_once()

    # 路径三：fresh
    def test_current_fresh_writes_cache(self):
        cm = make_cm()
        actions = [ActionStep(step_number=i, model_output=f"output{i}", action_output=f"result{i}") for i in range(2)]
        model = make_model('{"task_overview": "fresh步骤摘要"}')
        task = TaskStep(task="任务")
        cm._compress_current_with_cache(task, actions, model)
        assert cm._current_summary_cache is not None
        assert cm._current_summary_cache.end_steps == 2

    # 无 task_step 情形
    def test_current_no_task_step(self):
        cm = make_cm()
        actions = [ActionStep(step_number=1, model_output="output", action_output="result")]
        model = make_model('{"task_overview": "摘要"}')
        result = cm._compress_current_with_cache(None, actions, model)
        assert result is not None

    # 空 actions 返回 None
    def test_current_empty_actions_returns_none(self):
        cm = make_cm()
        model = make_model()
        assert cm._compress_current_with_cache(TaskStep(task="t"), [], model) is None
        model.assert_not_called()

    # 增量后 cache 的 anchor fingerprint 应更新为新末尾
    def test_current_incremental_updates_anchor_fingerprint(self):
        cm = make_cm()
        actions = [ActionStep(step_number=i, model_output=f"o{i}", action_output=f"r{i}") for i in range(3)]
        fp_old = ContextManager._action_fingerprint(actions[1])
        cm._current_summary_cache = CurrentSummaryCache("旧摘要", 2, fp_old)
        model = make_model('{"task_overview": "新摘要"}')
        cm._compress_current_with_cache(TaskStep(task="t"), actions, model)
        fp_new = ContextManager._action_fingerprint(actions[2])
        assert cm._current_summary_cache.anchor_fingerprint == fp_new

