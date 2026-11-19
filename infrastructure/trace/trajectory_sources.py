# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Bounded message identity evidence; source failures never imply complete capture."""

MAX_SOURCE_MESSAGES = 10_000


def source_ids(values):
    from .trajectory_store import business_id

    if not isinstance(values, list) or len(values) > MAX_SOURCE_MESSAGES:
        raise ValueError("Trajectory source identities exceed their budget")
    return {business_id(value) for value in values}


def initial_sources():
    return {
        "source_coverage_version": 1,
        "source_message_ids": [],
        "has_unlinked_executions": False,
        "source_coverage_limited": False,
        "source_history_gap": False,
        "source_coverage_verified": False,
    }


def register_source(meta, source):
    if meta.get("source_coverage_version") != 1:
        meta.update(initial_sources())
        meta["has_unlinked_executions"] = True
    if source is None:
        meta["has_unlinked_executions"] = True
        return
    registered = source_ids(meta["source_message_ids"])
    if source not in registered and len(registered) >= MAX_SOURCE_MESSAGES:
        meta["source_coverage_limited"] = True
        return
    registered.add(source)
    meta["source_message_ids"] = sorted(registered, key=int)


def unverified_sources(meta):
    return {"source_coverage_verified": False, "has_uncaptured_history": True, "latest_source_captured": None}


def verified_sources(meta, observed, upper=None):
    """Compare exact IDs, retaining a proven historical gap across later retries."""
    registered = source_ids(meta["source_message_ids"])
    observed = source_ids(observed)
    if upper is not None:
        if upper not in observed or any(int(value) > int(upper) for value in observed):
            raise ValueError(
                "Trajectory source receipt does not match its conversation"
            )
        registered = {value for value in registered if int(value) <= int(upper)}
    mismatch = observed != registered
    historical_gap = bool(meta.get("source_history_gap") or mismatch)
    unknown = bool(meta["has_unlinked_executions"] or meta["source_coverage_limited"])
    from_start = bool(
        observed
        and registered
        and min(observed, key=int) == min(registered, key=int)
        and not unknown
    )
    return {
        "captured_from_start": from_start,
        "has_uncaptured_history": historical_gap or unknown,
        "source_history_gap": historical_gap,
        "source_coverage_verified": True,
        "latest_source_captured": (max(observed, key=int) in registered) if observed and not unknown else None,
    }
