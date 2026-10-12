"""Reversible, batch-owned platform capacity probe.

Only an exact value installed by this case may be rolled back.  A different
live value means another actor changed the setting; refuse to overwrite it.
"""

from __future__ import annotations

import uuid

from shared.asset_registry import mark_asset_state, register_asset
from shared.http import assert_status, client

GIB = 1024 ** 3


def capacity_gb_from_overview(payload: dict) -> int | None:
    value = payload.get("platform_capacity_bytes")
    if value is None:
        return None
    if not isinstance(value, int) or value < 0 or value % GIB:
        raise RuntimeError("platform capacity cannot be restored exactly through the GB API")
    return value // GIB


async def begin_capacity_probe(identity, original: int | None) -> tuple[str, int]:
    expected = (original + 1) if original is not None else 1024
    key = f"api-040-{uuid.uuid4().hex}"
    register_asset(
        "global_capacity_snapshots", key, key, owner_case_id="API-040",
        state="CREATING",
        cleanup={
            "kind": "restore_platform_capacity",
            "identity": identity.id,
            "original": original,
            "expected": expected,
        },
    )
    return key, expected


async def restore_capacity_probe(identity, key: str, original: int | None, expected: int) -> None:
    async with client("config", token=identity.access_token) as api:
        current_response = await api.get("/platform/quota/overview")
        assert_status(current_response, 200)
        current = capacity_gb_from_overview(current_response.json())
        if current == original:
            mark_asset_state("global_capacity_snapshots", key, "DELETED")
            return
        if current != expected:
            raise RuntimeError("platform capacity changed by another actor; refusing rollback")
        if original is None:
            restored = await api.delete("/platform/quota/capacity")
        else:
            restored = await api.put("/platform/quota/capacity", json={"capacity_gb": original})
        assert_status(restored, 200)
        verified = await api.get("/platform/quota/overview")
        assert_status(verified, 200)
        if capacity_gb_from_overview(verified.json()) != original:
            raise AssertionError("platform capacity rollback did not restore the original value")
    mark_asset_state("global_capacity_snapshots", key, "DELETED")
