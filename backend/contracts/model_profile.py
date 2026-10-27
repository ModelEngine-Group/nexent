# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Trusted management-side outlet selection contracts from the public model baseline."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelProfileSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=200)
    revision: str = Field(min_length=1, max_length=100)


class ModelProfileProviderInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = Field(min_length=1, max_length=500)
    provider_id: str | None = Field(default=None, min_length=1, max_length=100)
    ssl_verify: bool = True
    timeout_seconds: int = Field(default=120, gt=0, lt=2**31)
    concurrency_limit: int | None = Field(default=None, gt=0, lt=2**31)


class ModelOutletContextPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    combined_window: int | None = Field(default=None, gt=0, lt=2**31, strict=True)
    input_limit: int | None = Field(default=None, gt=0, lt=2**31, strict=True)
    output_limit: int | None = Field(default=None, gt=0, lt=2**31, strict=True)


class ModelOutletContextConfigurationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    output_reserve_tokens: int | None = Field(default=None, gt=0, lt=2**31, strict=True)
    tokenizer_family: str | None = Field(default=None, min_length=1, max_length=100)
    capacity_source: str | None = Field(default=None, min_length=1, max_length=100)
    capability_profile_version: str | None = Field(default=None, min_length=1, max_length=100)


class ModelProfilePreviewRequest(BaseModel):
    """Selection inputs only; clients cannot author effective capabilities or bindings."""
    model_config = ConfigDict(extra="forbid")
    selection_mode: Literal["auto", "manual"] = "auto"
    model_profile: ModelProfileSelection | None = None
    provider_profile: ModelProfileSelection | None = None
    catalog_revision: str | None = Field(default=None, min_length=1, max_length=100)
    provider_info: ModelProfileProviderInfo
    request_model_id: str = Field(min_length=1, max_length=100)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    protocol_id: Literal["openai_chat_completions"] = "openai_chat_completions"
    authentication_scheme: Literal["bearer_token_v1", "no_auth_v1"] = "bearer_token_v1"
    parameter_values: dict[str, Any] = Field(default_factory=dict)
    extra_api_parameters: list[dict[str, Any]] = Field(default_factory=list)
    context_limits: ModelOutletContextPatch | None = None
    context_configuration: ModelOutletContextConfigurationPatch | None = None
