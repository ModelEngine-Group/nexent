# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from management.services.agent.prompt import (
    should_enable_automation_tool_policy,
)


def test_automation_tool_policy_is_empty_when_tool_is_unavailable():
    assert not should_enable_automation_tool_policy(["other_tool"])


def test_ut_be_fps_013_automation_policy_uses_final_tool_set():
    assert should_enable_automation_tool_policy(["create_scheduled_task_proposal"])
