# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Lightweight storage contracts with lazy legacy object-storage exports."""

from importlib import import_module


_EXPORTS = {
    "StorageClient": ("storage_client_base", "StorageClient"),
    "StorageConfig": ("storage_client_base", "StorageConfig"),
    "MinIOStorageConfig": ("minio_config", "MinIOStorageConfig"),
    "create_storage_client_from_config": ("storage_client_factory", "create_storage_client_from_config"),
    "MinIOStorageClient": ("minio", "MinIOStorageClient"),
    "StorageInterface": ("interfaces", "StorageInterface"),
    "RecordStore": ("interfaces", "RecordStore"),
    "ObjectStore": ("interfaces", "ObjectStore"),
    "VectorStore": ("interfaces", "VectorStore"),
    "KeyValueStore": ("interfaces", "KeyValueStore"),
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module, symbol = _EXPORTS[name]
    value = getattr(import_module(f".{module}", __name__), symbol)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_EXPORTS))
