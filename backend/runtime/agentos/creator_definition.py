# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Require the referenced released creator definition at the Runtime boundary."""

from fastapi import HTTPException

from infrastructure.rdb.system_agent_records import read_system_creator


def load_creator_definition(payload):
    reference = payload.system_agent
    if reference is None:
        return None
    row = read_system_creator(reference.agent_id, reference.version_no, payload.mode + "_main")
    if row is None:
        raise HTTPException(status_code=409, detail={"code": "AGENTOS_CREATOR_DEFINITION_UNAVAILABLE"})
    return row
