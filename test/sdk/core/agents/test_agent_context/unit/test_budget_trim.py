from factories import make_cm, make_pair
from loader import ActionStep

class TestBudgetTrimming:

    def test_trim_pairs_within_budget_returns_all(self):
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(3)]
        result = cm._trim_pairs_to_budget(pairs, max_tokens=99999)
        assert len(result) == 3

    def test_trim_pairs_empty_input(self):
        cm = make_cm()
        assert cm._trim_pairs_to_budget([], max_tokens=1000) == []

    def test_trim_pairs_keeps_at_least_last_when_all_overflow(self):
        """即使预算极小，至少保留最后一个 pair"""
        cm = make_cm()
        pairs = [make_pair("非常长的任务描述" * 50, "非常长的回答内容" * 50, i) for i in range(3)]
        result = cm._trim_pairs_to_budget(pairs, max_tokens=1, keep_first=False)
        assert len(result) == 1

    def test_trim_pairs_keep_first_true_keeps_first_pair(self):
        """keep_first=True 时第一个 pair 必须被保留"""
        cm = make_cm()
        pairs = [make_pair(f"task{i}", f"action{i}", i) for i in range(5)]
        # 设极小预算，只够放1个pair
        first_pair_tokens = cm._estimate_text_tokens(cm._pairs_to_text([pairs[0]]))
        result = cm._trim_pairs_to_budget(pairs, max_tokens=first_pair_tokens + 5, keep_first=True)
        assert result[0] == pairs[0]

    def test_trim_actions_within_budget_returns_all(self):
        cm = make_cm()
        actions = [ActionStep(step_number=i, model_output=f"output{i}") for i in range(3)]
        result = cm._trim_actions_to_budget(actions, task_text="", max_tokens=99999)
        assert len(result) == 3

    def test_trim_actions_empty_returns_empty(self):
        cm = make_cm()
        assert cm._trim_actions_to_budget([], task_text="", max_tokens=1000) == []

    def test_trim_actions_keeps_last_when_overflow(self):
        """极端预算下至少保留最后一个 action"""
        cm = make_cm()
        actions = [
            ActionStep(step_number=i, model_output="X" * 500, action_output="Y" * 500)
            for i in range(4)
        ]
        result = cm._trim_actions_to_budget(actions, task_text="", max_tokens=1)
        assert len(result) >= 1
        assert result[-1] is actions[-1]

    def test_trim_actions_skips_drop_that_splits_tool_call_and_observation(self):
        """当截断点会把 tool_calls 和 observations 拆散时，应跳过该截断点"""
        cm = make_cm()
        actions = [
            ActionStep(step_number=0, model_output="A" * 400, tool_calls=[{"name": "tool1"}]),
            ActionStep(step_number=1, model_output="B" * 400, observations="obs1"),
            ActionStep(step_number=2, model_output="C" * 400),
        ]
        # 预算设在 2 个 action 和 3 个 action 之间：
        # 正常情况下 drop=1 可以保留 [action1, action2]，但因为 action0 有 tool_calls
        # 且 action1 有 observations，该截断点被跳过，最终只能 drop=2，保留 [action2]
        two_act_tokens = cm._estimate_text_tokens(cm._actions_to_text(actions[1:]))
        three_act_tokens = cm._estimate_text_tokens(cm._actions_to_text(actions))
        max_tokens = two_act_tokens + (three_act_tokens - two_act_tokens) // 2

        result = cm._trim_actions_to_budget(actions, task_text="", max_tokens=max_tokens)
        assert result == [actions[2]]

    def test_trim_actions_allows_drop_when_no_tool_call_before_observation(self):
        """remaining[0] 有 observations，但前一个 action 没有 tool_calls，应允许截断"""
        cm = make_cm()
        actions = [
            ActionStep(step_number=0, model_output="A" * 400),  # 无 tool_calls
            ActionStep(step_number=1, model_output="B" * 400, observations="obs1"),
            ActionStep(step_number=2, model_output="C" * 400),
        ]
        two_act_tokens = cm._estimate_text_tokens(cm._actions_to_text(actions[1:]))
        three_act_tokens = cm._estimate_text_tokens(cm._actions_to_text(actions))
        max_tokens = two_act_tokens + (three_act_tokens - two_act_tokens) // 2

        result = cm._trim_actions_to_budget(actions, task_text="", max_tokens=max_tokens)
        assert result == [actions[1], actions[2]]

    def test_trim_actions_allows_drop_when_no_observation_after_tool_call(self):
        """actions[drop-1] 有 tool_calls，但 remaining[0] 没有 observations，应允许截断"""
        cm = make_cm()
        actions = [
            ActionStep(step_number=0, model_output="A" * 400, tool_calls=[{"name": "tool1"}]),
            ActionStep(step_number=1, model_output="B" * 400),  # 无 observations
            ActionStep(step_number=2, model_output="C" * 400),
        ]
        two_act_tokens = cm._estimate_text_tokens(cm._actions_to_text(actions[1:]))
        three_act_tokens = cm._estimate_text_tokens(cm._actions_to_text(actions))
        max_tokens = two_act_tokens + (three_act_tokens - two_act_tokens) // 2

        result = cm._trim_actions_to_budget(actions, task_text="", max_tokens=max_tokens)
        assert result == [actions[1], actions[2]]

    def test_trim_actions_chain_pairs_fallback_returns_complete_pair(self):
        """连续配对导致所有 suffix 截断点非法或超预算时，fallback 返回最后完整的 tool_call+observation 对"""
        cm = make_cm()
        actions = [
            ActionStep(step_number=0, model_output="A" * 400, tool_calls=[{"name": "t1"}]),
            ActionStep(step_number=1, model_output="B" * 400, observations="obs1"),
            ActionStep(step_number=2, model_output="C" * 400, tool_calls=[{"name": "t2"}]),
            ActionStep(step_number=3, model_output="D" * 400, observations="obs2"),
        ]
        result = cm._trim_actions_to_budget(actions, task_text="", max_tokens=1)
        # drop=1 skip(T0→O1), drop=2 [T2,O3] 超预算, drop=3 skip(T2→O3)
        # fallback 保留最后完整的一对 [T2, O3]
        assert result == [actions[2], actions[3]]

    def test_trim_actions_fallback_returns_pair_when_last_is_observation(self):
        """fallback 时若最后 action 是 observation 且前一个有 tool_calls，返回完整配对"""
        cm = make_cm()
        actions = [
            ActionStep(step_number=0, model_output="A" * 400),
            ActionStep(step_number=1, model_output="B" * 400, tool_calls=[{"name": "t1"}]),
            ActionStep(step_number=2, model_output="C" * 400, observations="obs1"),
        ]
        result = cm._trim_actions_to_budget(actions, task_text="", max_tokens=1)
        assert result == [actions[1], actions[2]]

    def test_trim_actions_fallback_returns_single_when_last_has_no_observation(self):
        """fallback 时若最后 action 没有 observations，只返回单个最后一个"""
        cm = make_cm()
        actions = [
            ActionStep(step_number=0, model_output="A" * 400),
            ActionStep(step_number=1, model_output="B" * 400),
            ActionStep(step_number=2, model_output="C" * 400),
        ]
        result = cm._trim_actions_to_budget(actions, task_text="", max_tokens=1)
        assert result == [actions[-1]]