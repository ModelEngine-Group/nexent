# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compile deployment policy into detached, application-owned Agent configs."""

from contracts.constants.environment import NEXENT_AGENT_CORE
from nexent.core.agents.contracts.adapter import UnsupportedAgentCoreConfig


def apply_agent_core_policy(config):
    """Keep saved definitions untouched; normalize only this run's Core options."""
    config.agent_core = NEXENT_AGENT_CORE
    if NEXENT_AGENT_CORE == "jiuwen":
        guardrail = config.verification_config.guardrail_config
        if guardrail is not None and guardrail.enabled:
            raise UnsupportedAgentCoreConfig("Jiuwen does not support the configured guardrail policy")
        config.enable_protocol_repair_retry = False
        config.provide_run_summary = False
        config.verification_config = config.verification_config.model_copy(update={"enabled": False})
    for child in config.worker_agents:
        apply_agent_core_policy(child)
    return config


def prepare_creator_core(run_info, *, tenant_id, user_id=None, user_context=None):
    """Resolve creator identity and the final model snapshot before execution."""
    run_info.tenant_id = tenant_id
    run_info.user_id = user_id
    run_info.user_context = user_context or {"tenant_id": tenant_id, "user_id": user_id}
    apply_agent_core_policy(run_info.agent_config)
    if run_info.agent_config.agent_core == "jiuwen":
        from management.services.model.runtime_options import compile_bound_model_profile

        model = next(m for m in run_info.model_config_list if m.cite_name == run_info.agent_config.model_name)
        model.prompt_cache = None
        model.resolved_profile = compile_bound_model_profile(model, run_info.agent_config)
    return run_info
