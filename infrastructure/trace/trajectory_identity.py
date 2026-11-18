# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Local invocation ownership follows actual Agent spans and framework identities."""

INVOCATION = "nexent.local.nexent.invocation_id"
PARENT_INVOCATION = "nexent.local.nexent.parent_invocation_id"


def invocation_attributes(attributes, parent_attributes, record_id, *, root=False):
    """Technical operations carry ownership without creating an Agent invocation."""
    owner = parent_attributes.get(INVOCATION)
    if root or str(attributes.get("openinference.span.kind", "")).upper() == "AGENT":
        framework_id = attributes.get("subagent.invocation_id")
        values = {
            INVOCATION: framework_id
            if isinstance(framework_id, str) and framework_id
            else record_id
        }
        if owner:
            values[PARENT_INVOCATION] = owner
        return values
    return {INVOCATION: owner} if owner else {}
