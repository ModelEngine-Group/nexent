# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Authorization for automatic memory operations."""

import logging

from contracts.constants.constants import DISABLE_AGENT_ID_KEY, DISABLE_USERAGENT_ID_KEY, MEMORY_SWITCH_KEY
from management.services.configuration.user.memory import get_user_configs

logger = logging.getLogger(__name__)


def memory_allowed_for_config(config: dict, agent_id: str | int) -> bool:
    return config[MEMORY_SWITCH_KEY] == "Y" and all(
        str(agent_id) not in config.get(key, ())
        for key in (DISABLE_AGENT_ID_KEY, DISABLE_USERAGENT_ID_KEY)
    )


def can_write_automatic_memory(
    tenant_id: str, user_id: str, agent_id: str | int, version_no: int | None = None,
) -> bool:
    try:
        return memory_allowed_for_config(get_user_configs(user_id), agent_id)
    except Exception as exc:
        logger.warning("event=memory_policy_unavailable error_type=%s", type(exc).__name__)
        return False
