import logging
from typing import Dict, List, Union

from consts.const import (
    MEMORY_SWITCH_KEY,
    MEMORY_AGENT_SHARE_KEY,
    DISABLE_AGENT_ID_KEY,
    DISABLE_USERAGENT_ID_KEY,
)
from consts.model import MemoryAgentShareMode
from database.memory_config_db import (
    get_all_configs_by_user_id,
    get_memory_config_info,
    insert_config,
    delete_config_by_config_id,
    update_config_by_id,
)
from nexent.core.agents.agent_model import MemoryContext, MemoryUserConfig
from utils.memory_utils import build_memory_config

logger = logging.getLogger("memory_config_service")

_SINGLE_TYPE = "single"
_MULTI_TYPE = "multi"


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _aggregate_records(records: List[Dict[str, Union[str, int]]]) -> Dict[str, Union[str, List[str]]]:
    """Aggregate DB rows -> {config_key: value_or_list}"""
    aggregated: Dict[str, Union[str, List[str]]] = {}
    for r in records:
        key = r["config_key"]
        if r.get("value_type") == _MULTI_TYPE:
            aggregated.setdefault(key, []).append(r["config_value"])
        else:
            aggregated[key] = r["config_value"]
    return aggregated


# ---------------------------------------------------------------------------
# Generic operations
# ---------------------------------------------------------------------------

def get_user_configs(user_id: str) -> Dict[str, Union[str, List[str]]]:
    """Return all config key-values for the user (multi values aggregated into list)."""
    return _aggregate_records(get_all_configs_by_user_id(user_id))


def _update_single_config(user_id: str, config_key: str, config_value: str) -> bool:
    """Create or update a single-type configuration entry."""
    record_list = get_memory_config_info(user_id, config_key)

    if not record_list:
        # Insert new record
        result = insert_config({
            "user_id": user_id,
            "config_key": config_key,
            "config_value": config_value,
            "value_type": _SINGLE_TYPE,
            "created_by": user_id,
            "updated_by": user_id,
        })
        if not result:
            logger.error(
                f"insert_config failed, user_id={user_id}, key={config_key}, value={config_value}"
            )
            return False
    else:
        # Update first record (there should be max one for single type)
        config_id = record_list[0]["config_id"]
        result = update_config_by_id(config_id, {
            "config_value": config_value,
            "updated_by": user_id,
        })
        if not result:
            logger.error(
                f"update_config_by_id failed, user_id={user_id}, key={config_key}, value={config_value}"
            )
            return False
    return True


def _add_multi_value(user_id: str, config_key: str, value: str) -> bool:
    """Add a value to a multi-type list if it does not exist."""
    record_list = get_memory_config_info(user_id, config_key)
    if any(r["config_value"] == value for r in record_list):
        # Already exists, nothing to do
        return True

    ok = insert_config({
        "user_id": user_id,
        "config_key": config_key,
        "config_value": value,
        "value_type": _MULTI_TYPE,
        "created_by": user_id,
        "updated_by": user_id,
    })
    if not ok:
        logger.error(
            f"insert_config failed, user_id={user_id}, key={config_key}, value={value}"
        )
    return ok


def _remove_multi_value(user_id: str, config_key: str, value: str) -> bool:
    """Soft-delete a specific value from a multi-type configuration list."""
    record_list = get_memory_config_info(user_id, config_key)
    for r in record_list:
        if r["config_value"] == value:
            ok = delete_config_by_config_id(r["config_id"], updated_by=user_id)
            if not ok:
                logger.error(
                    f"delete_config_by_config_id failed, user_id={user_id}, key={config_key}, value={value}"
                )
            return ok
    # Value not found → treat as success
    return True


# ---------------------------------------------------------------------------
# Public service helpers used by API layer
# ---------------------------------------------------------------------------

def get_memory_switch(user_id: str) -> bool:
    configs = get_user_configs(user_id)
    return configs.get(MEMORY_SWITCH_KEY, "N") == "Y"


def set_memory_switch(user_id: str, enabled: bool) -> bool:
    return _update_single_config(user_id, MEMORY_SWITCH_KEY, "Y" if enabled else "N")


# Agent share (single string among always/ask/never)
def get_agent_share(user_id: str) -> MemoryAgentShareMode:
    configs = get_user_configs(user_id)
    mode_str = configs.get(MEMORY_AGENT_SHARE_KEY, MemoryAgentShareMode.NEVER.value)
    try:
        return MemoryAgentShareMode(mode_str)
    except ValueError:
        # Unexpected value, default to NEVER
        return MemoryAgentShareMode.NEVER


def set_agent_share(user_id: str, mode: MemoryAgentShareMode) -> bool:
    return _update_single_config(user_id, MEMORY_AGENT_SHARE_KEY, mode.value)


# Disable agent id list (multi)
def get_disabled_agent_ids(user_id: str) -> List[str]:
    configs = get_user_configs(user_id)
    return configs.get(DISABLE_AGENT_ID_KEY, [])  # type: ignore[return-value]


def add_disabled_agent_id(user_id: str, agent_id: str) -> bool:
    return _add_multi_value(user_id, DISABLE_AGENT_ID_KEY, agent_id)


def remove_disabled_agent_id(user_id: str, agent_id: str) -> bool:
    return _remove_multi_value(user_id, DISABLE_AGENT_ID_KEY, agent_id)


# Disable user-agent id list (multi)

def get_disabled_useragent_ids(user_id: str) -> List[str]:
    configs = get_user_configs(user_id)
    return configs.get(DISABLE_USERAGENT_ID_KEY, [])  # type: ignore[return-value]


def add_disabled_useragent_id(user_id: str, ua_id: str) -> bool:
    return _add_multi_value(user_id, DISABLE_USERAGENT_ID_KEY, ua_id)


def remove_disabled_useragent_id(user_id: str, ua_id: str) -> bool:
    return _remove_multi_value(user_id, DISABLE_USERAGENT_ID_KEY, ua_id)


def build_memory_context(user_id: str, tenant_id: str, agent_id: str | int) -> MemoryContext:
    memory_user_config = MemoryUserConfig(
        memory_switch=get_memory_switch(user_id),
        agent_share_option=get_agent_share(user_id).value,
        disable_agent_ids=get_disabled_agent_ids(user_id),
        disable_user_agent_ids=get_disabled_useragent_ids(user_id),
    )
    return MemoryContext(
        user_config=memory_user_config,
        memory_config=build_memory_config(tenant_id),
        tenant_id=tenant_id,
        user_id=user_id,
        agent_id=str(agent_id),
    )