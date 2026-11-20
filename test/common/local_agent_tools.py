# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Construct a local tool without starting an agent run."""

from nexent.core.agents.cores.smolagents.agent import NexentAgent


def create_local_tool(config, observer=None):
    agent = object.__new__(NexentAgent)
    agent.observer = observer
    return agent.create_local_tool(config)
