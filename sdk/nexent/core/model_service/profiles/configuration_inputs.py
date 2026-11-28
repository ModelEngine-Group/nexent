# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"""Neutral inputs for profile selection and outlet compilation."""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

ThinkingControlFormat = Literal["profile_default", "enable_thinking", "thinking_type", "chat_template"]

class ModelProfileSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=200)
    revision: str = Field(min_length=1, max_length=100)

class ModelProfileProviderInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = Field(min_length=1, max_length=500)
    provider_id: Optional[str] = Field(default=None, min_length=1, max_length=100)
    ssl_verify: bool = True
    timeout_seconds: int = Field(default=120, gt=0, lt=2**31)
    concurrency_limit: Optional[int] = Field(default=None, gt=0, lt=2**31)

class ModelOutletContextPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    combined_window: Optional[int] = Field(default=None, gt=0, lt=2**31, strict=True)
    input_limit: Optional[int] = Field(default=None, gt=0, lt=2**31, strict=True)
    output_limit: Optional[int] = Field(default=None, gt=0, lt=2**31, strict=True)

class ModelOutletContextConfigurationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    output_reserve_tokens: Optional[int] = Field(default=None, gt=0, lt=2**31, strict=True)
    tokenizer_family: Optional[str] = Field(default=None, min_length=1, max_length=100)
    capacity_source: Optional[str] = Field(default=None, min_length=1, max_length=100)
    capability_profile_version: Optional[str] = Field(default=None, min_length=1, max_length=100)

class ModelProfilePreviewRequest(BaseModel):
    """Selection inputs only; clients cannot author effective capabilities or bindings."""
    model_config = ConfigDict(extra="forbid")
    selection_mode: Literal["auto", "manual"] = "auto"
    model_profile: Optional[ModelProfileSelection] = None
    provider_profile: Optional[ModelProfileSelection] = None
    catalog_revision: Optional[str] = Field(default=None, min_length=1, max_length=100)
    provider_info: ModelProfileProviderInfo
    request_model_id: str = Field(min_length=1, max_length=100)
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    protocol_id: Literal["openai_chat_completions"] = "openai_chat_completions"
    authentication_scheme: Literal["bearer_token_v1", "no_auth_v1"] = "bearer_token_v1"
    parameter_values: Dict[str, Any] = Field(default_factory=dict)
    extra_api_parameters: List[Dict[str, Any]] = Field(default_factory=list)
    http_headers: Dict[str, str] = Field(default_factory=dict, repr=False)
    context_limits: Optional[ModelOutletContextPatch] = None
    context_configuration: Optional[ModelOutletContextConfigurationPatch] = None
    thinking_control: Optional[ThinkingControlFormat] = None
    thinking_mode: Optional[Literal["default", "effort", "budget_tokens"]] = None
    native_tool_call_supported: Optional[bool] = Field(default=None, strict=True)


class ModelOutletProfileSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_revision: str = Field(min_length=1, max_length=100)
    model_profile: Optional[ModelProfileSelection] = None
    provider_profile: Optional[ModelProfileSelection] = None


class ModelOutletConnectionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: Optional[str] = Field(default=None, min_length=1, max_length=500)
    ssl_verify: Optional[bool] = None
    timeout_seconds: Optional[int] = Field(default=None, gt=0, lt=2**31, strict=True)
    concurrency_limit: Optional[int] = Field(default=None, gt=0, lt=2**31, strict=True)


class ModelOutletPatchRequest(BaseModel):
    connect_status: Optional[Literal["available", "unavailable"]] = None
    reset_parameters: bool = False
    profile_selection: Optional[ModelOutletProfileSelection] = None
    request_model_id: Optional[str] = Field(default=None, min_length=1, max_length=100)
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0, lt=2**31, strict=True)
    parameter_values: Dict[str, Any] = Field(default_factory=dict)
    delete_parameters: List[str] = Field(default_factory=list, max_length=128)
    connection: Optional[ModelOutletConnectionPatch] = None
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    api_key: Optional[str] = Field(default=None, max_length=500, repr=False)
    http_headers: Optional[Dict[str, Optional[str]]] = Field(default=None, repr=False)
    extra_api_parameters: Optional[List[Dict[str, Any]]] = None
    context_limits: Optional[ModelOutletContextPatch] = None
    context_configuration: Optional[ModelOutletContextConfigurationPatch] = None
    thinking_control: Optional[ThinkingControlFormat] = None
    thinking_mode: Optional[Literal["default", "effort", "budget_tokens"]] = None
    native_tool_call_supported: Optional[bool] = Field(default=None, strict=True)
