# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Normalize deployment Core options for a detached Agent configuration."""

from nexent.core.agents.contracts.adapter import UnsupportedAgentCoreConfig


def apply_agent_core_policy(config, core):
    """Keep saved definitions untouched; normalize only this run's Core options."""
    config.agent_core = core
    if core == "jiuwen":
        guardrail = config.verification_config.guardrail_config
        if guardrail is not None and guardrail.enabled:
            raise UnsupportedAgentCoreConfig("Jiuwen does not support the configured guardrail policy")
        config.enable_protocol_repair_retry = False
        config.provide_run_summary = False
        config.verification_config = config.verification_config.model_copy(update={"enabled": False})
    for child in config.worker_agents:
        apply_agent_core_policy(child, core)
    return config
