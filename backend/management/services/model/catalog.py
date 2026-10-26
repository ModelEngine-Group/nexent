# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Day-one capability profile catalog for ModelCapacityResolver.

Source of truth: W1 ADR at
`doc/working/context-management-workstreams/W1_ADR_Capability_Catalog_Storage_and_Fingerprint.md`.

This module owns the approved catalog data. The SDK resolver
(`sdk/nexent/core/models/capacity_resolver.py`) takes the catalog as a parameter;
it does not import this module directly. Backend services read CATALOG here and
pass it through to the resolver.

Changes to entries: bump the per-entry `capability_profile_version` integer
suffix AND `CATALOG_REVISION` in one PR. Numerical values must be re-verified
against provider documentation at PR merge time."""

from threading import RLock
from contracts.constants.constants import MODEL_CAPABILITY_CATALOG_DATA

_catalog_lock = RLock()

def _build_capability_catalog():
    from nexent.core.models.capacity_resolver import CapabilityProfile

    return {key: CapabilityProfile(**value) for key, value in MODEL_CAPABILITY_CATALOG_DATA.items()}

def __getattr__(name):
    """Expose one shared typed catalog without eager SDK initialization."""
    if name != "CATALOG":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    with _catalog_lock:
        if "CATALOG" not in globals():
            globals()["CATALOG"] = _build_capability_catalog()
        return globals()["CATALOG"]
