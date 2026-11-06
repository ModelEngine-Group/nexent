# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Populate recall data only for a product-created, case-owned Mock KB."""
from copy import deepcopy
import re

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict


class FixtureBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kb_id: str
    name: str


def install(module):
    @module.app.post("/_mock/owned-aidp-oracle")
    def populate(body: FixtureBody):
        kb = module._KNOWLEDGE_BASES.get(body.kb_id)
        if (not re.fullmatch(r"d4-aidp-[a-f0-9]{16}", body.name)
                or not re.fullmatch(r"aidp-kb-[a-f0-9]{8}", body.kb_id)
                or not kb or kb.get("kds_name") != body.name):
            raise HTTPException(409, "Target must be the exact product-created owned KB")
        chunks = deepcopy(module._CHUNKS_BY_KB["aidp-kb-product"])
        for chunk in chunks:
            chunk["metadata"]["knowledge_base_id"] = body.kb_id
        module._CHUNKS_BY_KB[body.kb_id] = chunks
        module._save_state()
        return {"kb_id": body.kb_id, "chunk_count": len(chunks)}
