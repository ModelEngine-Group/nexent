# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Compile deployment policy into detached, application-owned Agent configs."""

from contracts.constants.environment import NEXENT_AGENT_CORE
from infrastructure.agent_core_policy import apply_agent_core_policy as apply_deployed_core_policy


def apply_agent_core_policy(config):
    return apply_deployed_core_policy(config, NEXENT_AGENT_CORE)


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
