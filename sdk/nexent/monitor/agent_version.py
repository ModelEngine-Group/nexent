# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Attributes for the resolved version of one executing Agent."""


def valid_agent_version(value):
    """Preserve draft zero without coercing booleans, strings or fractional values."""
    return type(value) is int and 0 <= value <= 2**63 - 1


def agent_version_attributes(version_no, version_name=None):
    """Only attach a version label when the corresponding identity is known."""
    if not valid_agent_version(version_no):
        return {
            "nexent.availability.agent_version_no": "not_captured" if version_no is None else "invalid",
        }
    result = {"agent.version_no": version_no}
    if isinstance(version_name, str) and version_name.strip():
        result["agent.version_name"] = version_name
    return result
