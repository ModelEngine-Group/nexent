# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Contracts for the global and tenant tool denylist editors."""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

ToolName = Annotated[str, StringConstraints(min_length=1, max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
ToolRef = Annotated[str, StringConstraints(pattern=r"^(tool|mcp|skill):[1-9][0-9]{0,9}$")]
GlobalResourceRef = Annotated[str, StringConstraints(pattern=r"^(mcp|skill):.{1,100}$")]


class GlobalDenylist(BaseModel):
    tool_names: list[ToolName] = Field(default_factory=list, max_length=10000)
    resource_refs: list[GlobalResourceRef] = Field(default_factory=list, max_length=10000)


class TenantDenylist(BaseModel):
    resource_refs: list[ToolRef] = Field(max_length=10000)


class GlobalDenylistUpdate(BaseModel):
    revision: str
    tool_names: list[ToolName] = Field(default_factory=list, max_length=10000)
    resource_refs: list[GlobalResourceRef] | None = Field(default=None, max_length=10000)


class TenantDenylistUpdate(TenantDenylist):
    revision: str
