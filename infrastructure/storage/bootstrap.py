# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Trusted composition binds physical configuration to a restricted SDK port."""

from dataclasses import dataclass

from nexent.storage.errors import InvalidInput, ScopeDenied
from nexent.storage.interfaces import KeyValueStore
from nexent.storage.models import StorageScope

from infrastructure.redis.kv import RedisKeyValueConfig, RedisKeyValueStore


@dataclass(frozen=True)
class KVBinding:
    namespace: str
    config: RedisKeyValueConfig
    service_roles: frozenset[str]
    allow_system: bool = False

    def __post_init__(self):
        if not isinstance(self.service_roles, (set, frozenset, tuple, list)):
            raise InvalidInput()
        object.__setattr__(self, "service_roles", frozenset(self.service_roles))
        if (
            not isinstance(self.namespace, str)
            or not self.namespace.strip()
            or not self.service_roles
            or type(self.allow_system) is not bool
            or any(
                not isinstance(role, str) or not role.strip()
                for role in self.service_roles
            )
        ):
            raise InvalidInput()


def bind_key_value(
    binding: KVBinding, scope: StorageScope, *, required: frozenset[str] = frozenset()
) -> KeyValueStore:
    if (
        scope.service_role not in binding.service_roles
        or binding.namespace not in scope.namespaces
        or scope.system
        and not binding.allow_system
    ):
        raise ScopeDenied()
    RedisKeyValueStore.capabilities.require(*required)
    return RedisKeyValueStore(binding.config, scope, namespace=binding.namespace)
