# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Operations management for database-backed system configuration."""

import json
import logging

import redis
from configuration.catalog import (
    DEFAULT_CATALOG,
    ConfigValue,
    SystemConfigurationSnapshot,
)
from configuration.database import configuration_database
from configuration.repository import SystemConfigurationRepository
from configuration.runtime import CONFIGURATION_CHANGED, CONFIGURATION_CHANNEL
from contracts.constants.environment import REDIS_URL

logger = logging.getLogger(__name__)
repository = SystemConfigurationRepository()


def _catalog_items(snapshot: SystemConfigurationSnapshot, keys=None) -> list[dict]:
    selected = set(keys) if keys is not None else None
    return [
        {
            "key": item.key,
            "value": snapshot.get(item.key),
            "default_value": item.default,
            "kind": item.kind,
            "group": item.group,
            "label_key": item.label_key,
            "description_key": item.description_key,
            "unit_key": item.unit_key,
            "effect_key": item.effect_key,
            "recommendation_available": item.recommendation_rule is not None,
        }
        for item in DEFAULT_CATALOG.definitions
        if selected is None or item.key in selected
    ]


def list_system_configurations() -> list[dict]:
    with configuration_database.session() as session:
        snapshot = repository.load_snapshot(session)
    return _catalog_items(snapshot)


def save_system_configurations(changes: dict[str, ConfigValue], *, actor: str) -> dict:
    with configuration_database.session() as session:
        snapshot = repository.save_changes(session, changes, actor=actor)
    notification = "published"
    try:
        publish_configuration_change(sorted(changes))
    except Exception:  # noqa: BLE001 - commit and notification are independent
        notification = "degraded"
        logger.error("System configuration was saved but Redis notification failed")
    return {
        "items": _catalog_items(snapshot, changes.keys()),
        "notification": notification,
    }


def publish_configuration_change(changed_keys: list[str]) -> None:
    client = redis.Redis.from_url(
        REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        client.publish(
            CONFIGURATION_CHANNEL,
            json.dumps({"event": CONFIGURATION_CHANGED, "changed_keys": changed_keys}),
        )
    finally:
        client.close()
