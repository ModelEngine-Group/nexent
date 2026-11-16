# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorization for automatic memory operations."""

import logging

from contracts.constants.constants import (
    DISABLE_AGENT_ID_KEY,
    DISABLE_USERAGENT_ID_KEY,
    DREAMING_SWITCH_KEY,
    MEMORY_SWITCH_KEY,
)
from contracts.errors.exceptions import AgentNotFoundError
from management.db.agent.repository import search_agent_info_by_agent_id
from management.db.agent.version import query_current_version_no
from management.db.configuration.tenant import get_single_config_info
from management.services.configuration.user.memory import get_user_configs

logger = logging.getLogger(__name__)

TENANT_MEMORY_SWITCH_KEY = "TENANT_MEMORY_SWITCH"


def tenant_memory_enabled(tenant_id: str) -> bool:
    setting = get_single_config_info(tenant_id, TENANT_MEMORY_SWITCH_KEY)
    return not setting or setting.get("config_value") == "Y"


def memory_allowed_for_config(config: dict, agent_id: str | int) -> bool:
    return config[MEMORY_SWITCH_KEY] == "Y" and all(
        str(agent_id) not in config.get(key, ())
        for key in (DISABLE_AGENT_ID_KEY, DISABLE_USERAGENT_ID_KEY)
    )


def dreaming_allowed(tenant_id: str, user_id: str) -> bool:
    config = get_user_configs(user_id)
    return (
        config[MEMORY_SWITCH_KEY] == "Y"
        and config[DREAMING_SWITCH_KEY] == "Y"
        and tenant_memory_enabled(tenant_id)
    )


def source_agent_allows_memory(tenant_id: str, agent_id: str | int, version_no: int | None = None) -> bool:
    try:
        numeric_id = int(agent_id)
        if version_no is None:
            version_no = query_current_version_no(numeric_id, tenant_id) or 0
        info = search_agent_info_by_agent_id(numeric_id, tenant_id, version_no)
    except (ValueError, TypeError, AgentNotFoundError):
        return False
    return info.get("enable_memory") is not False


def can_write_automatic_memory(
    tenant_id: str, user_id: str, agent_id: str | int, version_no: int | None = None,
) -> bool:
    try:
        return (
            memory_allowed_for_config(get_user_configs(user_id), agent_id)
            and tenant_memory_enabled(tenant_id)
            and source_agent_allows_memory(tenant_id, agent_id, version_no)
        )
    except Exception as exc:
        logger.warning("event=memory_policy_unavailable error_type=%s", type(exc).__name__)
        return False
