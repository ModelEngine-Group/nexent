# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"""Immutable model descriptors and capacity suggestion contracts."""

import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from enum import Enum


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


ThinkingControlFormat = Literal["profile_default", "enable_thinking", "thinking_type", "chat_template"]


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


class ModelProfilePreviewProviderInfo(ModelProfileProviderInfo):
    base_url: str = Field(default="", max_length=500)


class ModelProfilePreviewInput(ModelProfilePreviewRequest):
    """Allow catalog-only previews without weakening create or probe requirements."""
    provider_info: ModelProfilePreviewProviderInfo
    display_name: Optional[str] = Field(default=None, max_length=100)
    request_model_id: str = Field(default="", max_length=100)


class ModelOutletProfileSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_revision: str = Field(min_length=1, max_length=100)
    model_profile: Optional[ModelProfileSelection] = None
    provider_profile: Optional[ModelProfileSelection] = None


class ModelOutletCreateRequest(ModelProfilePreviewRequest):
    check_receipt: Optional[str] = Field(default=None, max_length=1024, repr=False)
    api_key: Optional[str] = Field(default=None, max_length=500, repr=False)


class ModelOutletConnectionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: Optional[str] = Field(default=None, min_length=1, max_length=500)
    ssl_verify: Optional[bool] = None
    timeout_seconds: Optional[int] = Field(default=None, gt=0, lt=2**31, strict=True)
    concurrency_limit: Optional[int] = Field(default=None, gt=0, lt=2**31, strict=True)


class ModelOutletPatchRequest(BaseModel):
    reset_parameters: bool = False
    profile_selection: Optional[ModelOutletProfileSelection] = None
    request_model_id: Optional[str] = Field(default=None, min_length=1, max_length=100)
    check_receipt: Optional[str] = Field(default=None, max_length=1024, repr=False)
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


class ConversationModelPreferencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0, lt=2**31 - 1, strict=True)
    parameter_values: Dict[str, Any] = Field(default_factory=dict)
    delete_parameters: List[str] = Field(default_factory=list, max_length=128)


class ConversationModelSelectionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0, lt=2**31 - 1, strict=True)
    selected_model_id: int = Field(gt=0, lt=2**31, strict=True)


class ModelOutletMigrationReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0, lt=2**31, strict=True)


class ModelOutletValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outlet_id: Optional[int] = Field(default=None, gt=0, lt=2**31, strict=True)
    expected_revision: Optional[int] = Field(default=None, gt=0, lt=2**31, strict=True)
    draft: Optional[ModelOutletCreateRequest] = None
    patch: Optional[ModelOutletPatchRequest] = None

    @model_validator(mode="after")
    def require_single_source(self):
        if (self.outlet_id is None) == (self.draft is None):
            raise ValueError("Select exactly one draft or saved outlet")
        if self.outlet_id is None and self.expected_revision is not None:
            raise ValueError("A draft has no saved revision")
        if self.patch is not None and self.outlet_id is None:
            raise ValueError("A patch requires a saved outlet")
        if self.patch is not None and self.expected_revision not in (None, self.patch.expected_revision):
            raise ValueError("Conflicting saved revisions")
        return self


ProfileKey = tuple[str, str]
CapabilityProfileLike = Any


class CapacitySuggestionMatchKind(str, Enum):
    CATALOG_EXACT = "catalog_exact"
    CATALOG_FUZZY = "catalog_fuzzy"
    PROVIDER_DISCOVERY = "provider_discovery"
    LITELLM_LOOKUP = "litellm_lookup"
    NONE = "none"


class CapacitySuggestionConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class CapacitySuggestionFields:
    context_window_tokens: Optional[int] = None
    max_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    default_output_reserve_tokens: Optional[int] = None
    tokenizer_family: Optional[str] = None


@dataclass(frozen=True)
class CapacitySuggestionResult:
    suggestions: Optional[CapacitySuggestionFields]
    match_kind: CapacitySuggestionMatchKind
    match_confidence: Optional[CapacitySuggestionConfidence]
    match_explanation: str
    suggested_provider: Optional[str] = None
    canonical_model_name: Optional[str] = None
    capability_profile_version: Optional[str] = None
    capacity_source_on_accept: Optional[str] = None


@dataclass(frozen=True)
class ModelDescriptor:
    display_name: str = ""
    is_multimodal: bool = False


# Response models for model management
class ModelResponse(BaseModel):
    code: int = 200
    message: str = ""
    data: Any


class ModelRequest(BaseModel):
    model_factory: Optional[str] = "OpenAI-API-Compatible"
    model_name: str
    model_type: str
    api_key: Optional[str] = ""
    base_url: Optional[str] = ""
    max_tokens: Optional[int] = 0
    used_token: Optional[int] = 0
    display_name: Optional[str] = ""
    connect_status: Optional[str] = ""
    expected_chunk_size: Optional[int] = None
    maximum_chunk_size: Optional[int] = None
    chunk_batch: Optional[int] = None
    # STT specific fields
    model_appid: Optional[str] = None
    access_token: Optional[str] = None
    timeout_seconds: Optional[int] = None
    concurrency_limit: Optional[int] = None
    # W1 capacity fields (see W1 ADR). All nullable; resolver applies precedence.
    context_window_tokens: Optional[int] = None
    max_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    default_output_reserve_tokens: Optional[int] = None
    tokenizer_family: Optional[str] = None
    capacity_source: Optional[str] = None
    capability_profile_version: Optional[str] = None
    # v2.6.0 inference params (model-level defaults). Nullable; NULL means provider default.
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    # v2.6.0 fixed inference params without dedicated columns (key-value pairs
    # constrained by FIXED_INFERENCE_FIELDS_BY_TYPE). NULL means no extra params.
    extra_params: Optional[Dict[str, Any]] = None
    # W11 accept-signal fields (audit/metrics only — never persisted). Sent by
    # the frontend when the operator clicks "Use suggestion" and saves; the
    # app layer pops them before the dict reaches the service/DB layer and
    # forwards them to model_capacity_suggestion_accept_total.
    accepted_suggestion_match_kind: Optional[str] = None
    accepted_capability_profile_version: Optional[str] = None
    # Batch-import flow control (never persisted). The batch dialog creates
    # rows one HTTP call at a time; rows marked skip_default_backfill leave
    # default-model slots untouched so a single finalize call (after the
    # loop) can fill empty slots from the whole batch at once. Popped by
    # the app layer before the dict reaches the service/DB layer.
    skip_default_backfill: Optional[bool] = None


class BackfillDefaultsRequest(BaseModel):
    """Request payload for POST /model/backfill_defaults only.

    Finalizes default-model auto-configuration after a batch import: empty
    slots are filled from the best model among the given display names.
    Occupied slots (user- or system-configured) are never touched.
    """

    display_names: List[str] = Field(
        ..., description="Display names of the models created in the batch"
    )


class ModelProbeRequest(ModelRequest):
    """Request payload for POST /model/temporary_healthcheck only.

    Extends ModelRequest with probe-only fields. Never send this to the
    create/update endpoints: they spread model_dump() straight into
    INSERT/UPDATE column lists, so any field that is not a real
    model_record_t column makes SQLAlchemy raise "Unconsumed column names"
    (and a field matching a column name would inject wrong data — the
    model_id NULL primary-key bug).
    """

    # Edit-dialog connectivity probes omit the stored api_key (the backend
    # never returns it to the client). When set, /temporary_healthcheck falls
    # back to the persisted key for this model instead of probing with the
    # "sk-no-api-key" placeholder.
    probe_model_id: Optional[int] = None


class CapacitySuggestionRequestFields(BaseModel):
    context_window_tokens: Optional[int] = None
    max_input_tokens: Optional[int] = None
    max_output_tokens: Optional[int] = None
    default_output_reserve_tokens: Optional[int] = None
    tokenizer_family: Optional[str] = None


class ModelCapacitySuggestionRequest(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=512)
    base_url: Optional[str] = None
    provider_hint: Optional[str] = None
    api_key: Optional[str] = None
    model_type: Optional[str] = None


class ModelCapacitySuggestionResponse(BaseModel):
    suggestions: Optional[CapacitySuggestionRequestFields] = None
    reasoning_capability: Optional["ReasoningCapability"] = None
    match_kind: Literal[
        "catalog_exact", "catalog_fuzzy", "provider_discovery", "litellm_lookup", "none"
    ]
    match_confidence: Optional[Literal["high", "medium", "low"]] = None
    match_explanation: str
    suggested_provider: Optional[str] = None
    canonical_model_name: Optional[str] = None
    capability_profile_version: Optional[str] = None
    capacity_source_on_accept: Optional[Literal["operator"]] = None


class CapacityCoverageBareModel(BaseModel):
    model_id: int
    model_name: str
    model_factory: Optional[str] = None
    model_type: Literal["llm", "vlm", "vlm2", "vlm3", "vlm4"]
    max_tokens: Optional[int] = None
    suggestion_available: bool = False


class CapacityCoverageResponse(BaseModel):
    total_llm_vlm: int
    bare_count: int
    bare_models: List[CapacityCoverageBareModel] = Field(default_factory=list)


class ProviderModelRequest(BaseModel):
    # min_length=1 rejects the blank provider at the API boundary (422) instead
    # of letting it reach the discovery fetch, where a provider-less request can
    # only fail as an opaque upstream connection error.
    provider: str = Field(..., min_length=1)
    # v2.6.0: model_type is now optional. When omitted, the backend fetches all
    # models from the OpenAI-compatible /v1/models endpoint and infers each
    # model's type from its name via _infer_model_type_from_name. When provided,
    # behavior is unchanged (filter by type).
    model_type: Optional[str] = None
    api_key: Optional[str] = ""
    base_url: Optional[str] = ""
    # TLS certificate verification for the discovery fetch. Defaults to the
    # safe value; operators pointing at self-signed internal endpoints must
    # opt out explicitly instead of verification being silently disabled.
    ssl_verify: bool = True

    timeout_seconds: int = Field(default=120, gt=0, lt=2**31)
    http_headers: Dict[str, str] = Field(default_factory=dict, repr=False)


class BatchCreateModelsRequest(BaseModel):
    api_key: str
    models: List[Dict]
    provider: str
    type: str


# Configuration models
class ModelApiConfig(BaseModel):
    apiKey: str
    modelUrl: str


class SingleModelConfig(BaseModel):
    modelName: str
    displayName: str
    apiConfig: Optional[ModelApiConfig] = None
    dimension: Optional[int] = None


class STTModelConfig(BaseModel):
    """STT model specific configuration with factory, appid, and access token fields"""

    modelName: str
    displayName: str
    apiConfig: Optional[ModelApiConfig] = None
    modelFactory: Optional[str] = None
    modelAppid: Optional[str] = None
    accessToken: Optional[str] = None


def _empty_model_config() -> SingleModelConfig:
    return SingleModelConfig(
        modelName="", displayName="", apiConfig=ModelApiConfig(apiKey="", modelUrl="")
    )


class TTSModelConfig(BaseModel):
    """TTS model specific configuration with factory, appid, and access token fields"""

    modelName: str
    displayName: str
    apiConfig: Optional[ModelApiConfig] = None
    modelFactory: Optional[str] = None
    modelAppid: Optional[str] = None
    accessToken: Optional[str] = None


class ModelConfig(BaseModel):
    llm: SingleModelConfig
    embedding: SingleModelConfig
    multiEmbedding: SingleModelConfig
    rerank: SingleModelConfig
    vlm: SingleModelConfig
    vlm2: SingleModelConfig = Field(default_factory=_empty_model_config)
    vlm3: SingleModelConfig = Field(default_factory=_empty_model_config)
    vlm4: SingleModelConfig = Field(default_factory=_empty_model_config)
    stt: STTModelConfig
    tts: TTSModelConfig


class AppConfig(BaseModel):
    iconType: str
    iconKey: Optional[str] = "search"
    customIconUrl: Optional[str] = None
    avatarUri: Optional[str] = None
    modelEngineEnabled: bool = False
    datamateUrl: Optional[str] = None


class GlobalConfig(BaseModel):
    app: AppConfig
    models: ModelConfig


# Manage Tenant Model Data Models
# ---------------------------------------------------------------------------
class ManageTenantModelListRequest(BaseModel):
    """Request model for listing models in a specific tenant (manage operation)"""

    tenant_id: str = Field(
        ..., min_length=1, description="Target tenant ID to query models for"
    )
    model_type: Optional[str] = Field(
        None, description="Filter by model type (e.g., 'llm', 'embedding')"
    )
    page: int = Field(1, ge=1, description="Page number for pagination")
    page_size: int = Field(20, ge=1, le=100, description="Items per page")


class ManageTenantModelListResponse(BaseModel):
    """Response model for tenant model list query"""

    tenant_id: str = Field(..., description="Tenant identifier")
    tenant_name: str = Field(..., description="Tenant display name")
    models: List[Dict[str, Any]] = Field(
        default_factory=list, description="List of models for this tenant"
    )
    total: int = Field(0, description="Total number of models")
    page: int = Field(1, description="Current page number")
    page_size: int = Field(20, description="Items per page")
    total_pages: int = Field(0, description="Total number of pages")


class _ManageTenantModelCommonFields(BaseModel):
    """Optional fields shared by the tenant manage create/update requests.

    Kept as a mixin so the two request models cannot drift apart; the wire
    contract (all Optional, default None) is identical for both operations.
    """

    model_factory: Optional[str] = Field(
        None, description="Model factory/vendor for the model"
    )
    expected_chunk_size: Optional[int] = Field(
        None, description="Expected chunk size for embedding models"
    )
    maximum_chunk_size: Optional[int] = Field(
        None, description="Maximum chunk size for embedding models"
    )
    chunk_batch: Optional[int] = Field(None, description="Batch size for chunking")
    # STT specific fields
    model_appid: Optional[str] = Field(
        None, description="Application ID for STT models (e.g., Volcano Engine)"
    )
    access_token: Optional[str] = Field(
        None, description="Access token for STT models (e.g., Volcano Engine)"
    )
    timeout_seconds: Optional[int] = Field(
        None, description="Request timeout in seconds"
    )
    concurrency_limit: Optional[int] = Field(
        None, description="Maximum concurrent requests for this model"
    )
    # W1 capacity fields (see W1 ADR). All nullable; resolver applies precedence.
    context_window_tokens: Optional[int] = Field(
        None, description="Total combined input/output context window in tokens"
    )
    max_input_tokens: Optional[int] = Field(
        None, description="Provider hard input-token limit"
    )
    max_output_tokens: Optional[int] = Field(
        None, description="Provider-supported completion output cap"
    )
    default_output_reserve_tokens: Optional[int] = Field(
        None, description="Default output allowance reserved per request"
    )
    tokenizer_family: Optional[str] = Field(
        None, description="Token-counting strategy or tokenizer identifier"
    )
    capacity_source: Optional[str] = Field(
        None, description="Source of the persisted capacity value"
    )
    capability_profile_version: Optional[str] = Field(
        None, description="Version of the approved capability profile"
    )
    # v2.6.0 inference params (model-level defaults). Nullable; NULL means provider default.
    temperature: Optional[float] = Field(
        None, description="Default sampling temperature for LLM/VLM models"
    )
    top_p: Optional[float] = Field(
        None, description="Default nucleus sampling probability for LLM/VLM models"
    )
    extra_params: Optional[Dict[str, Any]] = Field(
        None,
        description="Fixed inference params without dedicated columns (constrained by FIXED_INFERENCE_FIELDS_BY_TYPE)",
    )
    # W11 accept-signal fields. Same audit-only contract as ModelRequest:
    # the app layer pops them off model_data before the dict reaches the
    # service/DB layer and forwards them to
    # model_capacity_suggestion_accept_total. Declared here so Pydantic's
    # default extra="ignore" does not silently drop the wire signal --
    # without these declarations the SLO numerator misses every accept
    # that lands via the SU/asset-owner surface.
    accepted_suggestion_match_kind: Optional[str] = Field(
        None, description="Audit-only: catalog match_kind the operator accepted"
    )
    accepted_capability_profile_version: Optional[str] = Field(
        None,
        description="Audit-only: capability profile version of the accepted suggestion",
    )


class ManageTenantModelCreateRequest(_ManageTenantModelCommonFields):
    """Request model for creating a model in a specific tenant (admin/manage operation)"""

    tenant_id: str = Field(
        ..., min_length=1, description="Target tenant ID to create model for"
    )
    model_repo: Optional[str] = Field("", description="Model repository path")
    model_name: str = Field(..., description="Model name")
    model_type: str = Field(
        ..., description="Model type (e.g., 'llm', 'embedding', 'vlm', 'stt')"
    )
    api_key: Optional[str] = Field("", description="API key for the model")
    base_url: Optional[str] = Field("", description="Base URL for the model API")
    max_tokens: Optional[int] = Field(0, description="Maximum tokens for the model")
    display_name: Optional[str] = Field("", description="Display name for the model")


class ManageTenantModelUpdateRequest(_ManageTenantModelCommonFields):
    """Request model for updating a model in a specific tenant (admin/manage operation)"""

    tenant_id: str = Field(
        ..., min_length=1, description="Target tenant ID to update model for"
    )
    current_display_name: str = Field(
        ..., description="Current display name of the model to update"
    )
    model_repo: Optional[str] = Field(None, description="Model repository path")
    model_name: Optional[str] = Field(None, description="Model name")
    model_type: Optional[str] = Field(None, description="Model type")
    api_key: Optional[str] = Field(None, description="API key for the model")
    base_url: Optional[str] = Field(None, description="Base URL for the model API")
    max_tokens: Optional[int] = Field(None, description="Maximum tokens for the model")
    display_name: Optional[str] = Field(
        None, description="New display name for the model"
    )


class ManageTenantModelDeleteRequest(BaseModel):
    """Request model for deleting a model from a specific tenant (admin/manage operation)"""

    tenant_id: str = Field(
        ..., min_length=1, description="Target tenant ID to delete model from"
    )
    display_name: str = Field(..., description="Display name of the model to delete")


class ManageTenantModelHealthcheckRequest(BaseModel):
    """Request model for checking model connectivity in a specific tenant (admin/manage operation)"""

    tenant_id: str = Field(
        ..., min_length=1, description="Target tenant ID to check model connectivity"
    )
    display_name: str = Field(..., description="Display name of the model to check")
    model_type: Optional[str] = Field(
        None,
        description="Model type to disambiguate models with the same display name",
    )


class ManageBatchCreateModelsRequest(BaseModel):
    """Request model for batch creating/updating models in a specific tenant (admin/manage operation)"""

    tenant_id: str = Field(
        ..., min_length=1, description="Target tenant ID to batch create models for"
    )
    provider: str = Field(
        ..., description="Model provider (e.g., 'silicon', 'modelengine')"
    )
    type: str = Field(..., description="Model type (e.g., 'llm', 'embedding')")
    api_key: str = Field("", description="API key for the models")
    models: List[Dict[str, Any]] = Field(
        default_factory=list, description="List of models to create/update"
    )


class ManageProviderModelListRequest(BaseModel):
    """Request model for listing provider models in a specific tenant (admin/manage operation)"""

    tenant_id: str = Field(
        ..., min_length=1, description="Target tenant ID to query provider models for"
    )
    provider: str = Field(
        ..., description="Model provider (e.g., 'silicon', 'modelengine')"
    )
    model_type: str = Field(..., description="Model type (e.g., 'llm', 'embedding')")


class ManageProviderModelCreateRequest(BaseModel):
    """Request model for creating provider models in a specific tenant (admin/manage operation)"""

    tenant_id: str = Field(
        ..., min_length=1, description="Target tenant ID to create provider models for"
    )
    provider: str = Field(
        ..., min_length=1, description="Model provider (e.g., 'silicon', 'modelengine')"
    )
    # v2.6.0: model_type is now optional. When omitted, returns all models and
    # infers type from model name. When provided, behavior is unchanged.
    model_type: Optional[str] = Field(None, description="Model type (e.g., 'llm', 'embedding'). Optional since v2.6.0.")
    api_key: Optional[str] = Field('', description="API key for the provider")
    base_url: Optional[str] = Field('', description="Base URL for the provider API")
    ssl_verify: bool = True
    timeout_seconds: int = Field(default=120, gt=0, lt=2**31)
    http_headers: Dict[str, str] = Field(default_factory=dict, repr=False)


# =============================================================================
# Model Catalog (预置模型目录) 相关数据模型
# =============================================================================


class ReasoningControl(BaseModel):
    """One reasoning control exposed by the provider catalog."""

    type: Literal["toggle", "effort", "budget_tokens"]
    values: List[str] = Field(default_factory=list)
    min: Optional[int] = Field(default=None, ge=0)
    max: Optional[int] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_control(self) -> "ReasoningControl":
        if self.type == "effort" and not self.values:
            raise ValueError("Effort reasoning control must declare values")
        if self.type == "budget_tokens":
            if self.min is None or self.max is None or self.min > self.max:
                raise ValueError(
                    "Budget-token reasoning control must declare a valid min/max range"
                )
        return self


class ReasoningCapability(BaseModel):
    """Explicit reasoning control capability declared by the model catalog."""

    status: Literal["supported", "unsupported", "unknown"] = "unknown"
    control: Literal["toggle", "effort", "budget_tokens"] = "effort"
    levels: List[
        Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
    ] = Field(default_factory=list)
    default: Optional[
        Literal["auto", "none", "minimal", "low", "medium", "high", "xhigh", "max"]
    ] = None
    wire_format: Literal["reasoning_effort", "thinking_toggle", "thinking_budget"] = (
        "reasoning_effort"
    )
    effort_budgets: Dict[str, int] = Field(default_factory=dict)
    controls: List[ReasoningControl] = Field(default_factory=list)
    provider_id: Optional[str] = None
    budget_wire_format: Optional[Literal["thinking_object", "thinking_budget"]] = None
    toggle_wire_format: Optional[
        Literal["thinking_object", "enable_thinking", "chat_template"]
    ] = None
    matched_api: Optional[str] = None
    matched_model_id: Optional[str] = None
    source: Literal["catalog", "models_dev", "operator", "unknown"] = "unknown"

    @model_validator(mode="after")
    def validate_levels(self) -> "ReasoningCapability":
        if self.status == "supported" and self.control == "effort" and not self.levels:
            raise ValueError(
                "Effort reasoning capability must declare at least one level"
            )
        if (
            self.default is not None
            and self.default != "auto"
            and self.default not in self.levels
        ):
            raise ValueError("Reasoning default must be included in reasoning levels")
        if any(level not in self.levels for level in self.effort_budgets):
            raise ValueError(
                "Reasoning budget keys must be included in reasoning levels"
            )
        if any(value < 1024 for value in self.effort_budgets.values()):
            raise ValueError("Reasoning budgets must be at least 1024 tokens")
        if self.status == "supported" and self.wire_format == "thinking_budget":
            missing_budgets = {
                level
                for level in self.levels
                if level != "none" and level not in self.effort_budgets
            }
            if missing_budgets:
                raise ValueError(
                    "Thinking-budget reasoning capability must declare a budget for every enabled level"
                )
        if self.status != "supported":
            self.levels = []
            self.default = None
            self.effort_budgets = {}
            self.controls = []
        return self


# Canonical values accepted by the model-level reasoning default.  The
# provider catalog still decides which values are valid for a specific model.
REASONING_EFFORT_VALUES = frozenset(
    {"auto", "none", "minimal", "low", "medium", "high", "xhigh", "max"}
)


class ModelCatalogProfile(BaseModel):
    """从预置模型目录中读取的单个模型的完整配置描述。

    字段设计与 ModelRecord 表列一一对应，但去掉了 api_key（用户输入）、
    tenant_id（多租户隔离）、connect_status（运行时状态）等运行时字段。
    """

    model_type: str = Field(
        ...,
        description="Model type: llm / embedding / multi_embedding / rerank / vlm / vlm2 / vlm3 / stt / tts",
    )
    display_name: Optional[str] = Field(
        None, description="UI display name (fallback to model_name)"
    )
    base_url: Optional[str] = Field(
        None, description="Provider-level base_url or model-level override"
    )
    model_factory: Optional[str] = Field(
        None,
        description="Model factory / compatibility format, e.g. OpenAI-API-Compatible, VolcEngine-STT",
    )
    context_window_tokens: Optional[int] = Field(
        None, gt=0, description="Combined input+output context window in tokens"
    )
    max_input_tokens: Optional[int] = Field(
        None, gt=0, description="Maximum input tokens allowed by the provider"
    )
    max_output_tokens: Optional[int] = Field(
        None, gt=0, description="Maximum output / completion tokens"
    )
    default_output_reserve_tokens: Optional[int] = Field(
        None, gt=0, description="Default output token reserve before input budget calc"
    )
    tokenizer_family: Optional[str] = Field(
        None, description="Tokenizer family identifier mapped via tokenizer_registry"
    )
    expected_chunk_size: Optional[int] = Field(
        None,
        gt=0,
        description="Expected chunk size (embedding / multi_embedding models)",
    )
    maximum_chunk_size: Optional[int] = Field(
        None,
        gt=0,
        description="Maximum chunk size (embedding / multi_embedding models)",
    )
    chunk_batch: Optional[int] = Field(
        None,
        gt=0,
        description="Concurrent batch size for embedding requests during chunking",
    )
    dimension: Optional[int] = Field(
        None, gt=0, description="Embedding vector dimension"
    )
    timeout_seconds: Optional[int] = Field(
        None, gt=0, description="Per-request timeout in seconds"
    )
    concurrency_limit: Optional[int] = Field(
        None, gt=0, description="Maximum concurrent requests for this model"
    )
    capability_profile_version: Optional[str] = Field(
        None, description="Approved provider/model capability profile version"
    )
    reasoning_capability: Optional[ReasoningCapability] = Field(
        None,
        description="Explicit reasoning control capability for this model",
    )
    requires_appid: bool = Field(
        False, description="Whether the model requires model_appid auth (STT/TTS)"
    )
    requires_access_token: bool = Field(
        False, description="Whether the model requires access_token auth (STT/TTS)"
    )
    forced_temperature: Optional[float] = Field(
        None,
        description=(
            "Sampling temperature the provider enforces for this model "
            "(reasoning-only models like kimi-k3 reject any other value). "
            "Auto-filled into model records as the default temperature."
        ),
    )


class ModelCatalogProviderInfo(BaseModel):
    """某个 provider 在预置目录中的摘要信息，用于 API 返回给前端做展示。"""

    id: str = Field(
        ..., description="Provider id key (silicon / dashscope / openai / ...)"
    )
    display_name: str = Field(
        ..., description="Human-readable provider name shown in UI"
    )
    base_url: str = Field(..., description="Provider-level default base_url")
    supported_types: List[str] = Field(
        default_factory=list,
        description="Model types the catalog provides for this provider (llm/vlm/embedding/...)",
    )
    model_count: int = Field(
        0, description="Number of models in catalog for this provider"
    )


# =============================================================================
# v2.6.0: 按类型固定字段规格 (前后端共用)
# =============================================================================


class FieldSpec(BaseModel):
    """Specification of a single fixed inference field for advanced settings UI.

    Shared by backend validation and frontend dynamic rendering so the field
    set is defined in exactly one place.
    """

    key: str = Field(
        ..., description="Field key (snake_case), e.g. 'temperature', 'top_p'"
    )
    label: str = Field(..., description="Human-readable label shown in UI")
    type: str = Field(
        ...,
        description="Field type: 'str' | 'int' | 'float' | 'bool' | 'select' | 'array_str'",
    )
    range: Optional[List[float]] = Field(
        None,
        description="For numeric fields: [min, max]. None means no range constraint.",
    )
    default: Optional[Any] = Field(
        None, description="Default value when user does not set it"
    )
    options: Optional[List[str]] = Field(
        None, description="For 'select' type: allowed option values"
    )
    max_items: Optional[int] = Field(
        None, description="For 'array_str' type: maximum number of items"
    )


# Shared FieldSpec groups reused across model types. Keeping them as module
# constants removes the duplicated spec blocks that previously appeared
# verbatim in the llm/vlm/vlm2/vlm3, embedding/multi_embedding and stt/tts
# entries below. Each entry below copies the lists so runtime mutation of one
# model type's spec list cannot leak into another.
_COMMON_CAPACITY_FIELD_SPECS = [
    FieldSpec(key="context_window_tokens", label="上下文窗口", type="int"),
    FieldSpec(key="max_input_tokens", label="最大输入Token数", type="int"),
    FieldSpec(key="max_output_tokens", label="最大输出Token数", type="int"),
    FieldSpec(key="default_output_reserve_tokens", label="输出预留Token数", type="int"),
    FieldSpec(key="tokenizer_family", label="Tokenizer", type="str"),
]

_DISPLAY_NAME_FIELD_SPEC = FieldSpec(key="display_name", label="显示名称", type="str")

_EMBEDDING_FIELD_SPECS = [
    FieldSpec(key="display_name", label="显示名称", type="str"),
    FieldSpec(key="dimension", label="向量维度", type="int"),
    FieldSpec(key="expected_chunk_size", label="期望块大小", type="int"),
    FieldSpec(key="maximum_chunk_size", label="最大块大小", type="int"),
    FieldSpec(key="chunk_batch", label="块批大小", type="int"),
]

# Fixed inference field specs by model type. Each model type has its own set of
# fixed advanced-settings fields. Fields with dedicated DB columns
# (see _FIELDS_WITH_DEDICATED_COLUMN) are persisted as top-level columns; the
# rest are persisted to the extra_params JSONB column. enable_thinking is
# stored in extra_params to avoid a DB migration — the runtime adapter is
# responsible for translating it to the provider-specific request shape
# (e.g. Qwen3 chat_template_kwargs={"enable_thinking": ...}).
FIXED_INFERENCE_FIELDS_BY_TYPE: Dict[str, List[FieldSpec]] = {
    "llm": [
        _DISPLAY_NAME_FIELD_SPEC,
        *list(_COMMON_CAPACITY_FIELD_SPECS),
        FieldSpec(key="temperature", label="温度", type="float", range=[0.0, 2.0]),
        FieldSpec(key="top_p", label="Top P", type="float", range=[0.0, 1.0]),
        FieldSpec(key="enable_thinking", label="深度思考", type="bool"),
    ],
    "vlm": [_DISPLAY_NAME_FIELD_SPEC, *list(_COMMON_CAPACITY_FIELD_SPECS)],
    "vlm2": [_DISPLAY_NAME_FIELD_SPEC, *list(_COMMON_CAPACITY_FIELD_SPECS)],
    "vlm3": [_DISPLAY_NAME_FIELD_SPEC, *list(_COMMON_CAPACITY_FIELD_SPECS)],
    "embedding": list(_EMBEDDING_FIELD_SPECS),
    "multi_embedding": list(_EMBEDDING_FIELD_SPECS),
    "rerank": [
        FieldSpec(key="display_name", label="显示名称", type="str"),
        FieldSpec(key="max_tokens", label="最大Token数", type="int"),
    ],
    "stt": [
        FieldSpec(key="display_name", label="显示名称", type="str"),
        FieldSpec(
            key="model_factory",
            label="STT服务商",
            type="select",
            options=["dashscope", "volcengine"],
        ),
        FieldSpec(key="model_appid", label="AppID", type="str"),
        FieldSpec(key="access_token", label="Access Token", type="str"),
    ],
    "tts": [
        FieldSpec(key="display_name", label="显示名称", type="str"),
        FieldSpec(
            key="model_factory",
            label="TTS服务商",
            type="select",
            options=["dashscope", "volcengine"],
        ),
        FieldSpec(key="model_appid", label="AppID", type="str"),
        FieldSpec(key="access_token", label="Access Token", type="str"),
        FieldSpec(key="max_tokens", label="最大Token数", type="int"),
    ],
}


# Fields with dedicated DB columns. The remaining fields in
# FIXED_INFERENCE_FIELDS_BY_TYPE are persisted to extra_params JSONB.
_FIELDS_WITH_DEDICATED_COLUMN = frozenset(
    {
        "display_name",
        "temperature",
        "top_p",
        "context_window_tokens",
        "max_input_tokens",
        "max_output_tokens",
        "default_output_reserve_tokens",
        "tokenizer_family",
        "dimension",
        "expected_chunk_size",
        "maximum_chunk_size",
        "chunk_batch",
        "model_factory",
        "model_appid",
        "access_token",
        "max_tokens",
    }
)


def get_extra_param_keys_for_type(model_type: str) -> List[str]:
    """Return the list of field keys that should be stored in extra_params JSONB
    for the given model type (i.e., fields without a dedicated DB column).
    """
    specs = FIXED_INFERENCE_FIELDS_BY_TYPE.get(model_type, [])
    keys = [s.key for s in specs if s.key not in _FIELDS_WITH_DEDICATED_COLUMN]
    if model_type in {"llm", "chat"}:
        # Stored in the existing JSONB column so this feature remains
        # backwards-compatible with installations that have no migration.
        keys.append("reasoning_effort")
        keys.append("reasoning_budget_tokens")
    return keys


_INVALID_CUSTOM_VALUE = object()


def _clean_custom_json_value(value: Any) -> Any:
    """Return a JSON-compatible copy of a custom parameter value.

    Custom provider parameters intentionally accept the complete JSON value
    space, not only scalar values. Non-finite floats and Python-only values
    are rejected because PostgreSQL JSONB and the model request body cannot
    represent them reliably.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _INVALID_CUSTOM_VALUE
    if isinstance(value, list):
        cleaned_list = []
        for item in value:
            cleaned_item = _clean_custom_json_value(item)
            if cleaned_item is _INVALID_CUSTOM_VALUE:
                return _INVALID_CUSTOM_VALUE
            cleaned_list.append(cleaned_item)
        return cleaned_list
    if isinstance(value, dict):
        cleaned_dict: Dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                return _INVALID_CUSTOM_VALUE
            cleaned_item = _clean_custom_json_value(item)
            if cleaned_item is _INVALID_CUSTOM_VALUE:
                return _INVALID_CUSTOM_VALUE
            cleaned_dict[key] = cleaned_item
        return cleaned_dict
    return _INVALID_CUSTOM_VALUE


def _clean_custom_params(value: Any, logger) -> Optional[Dict[str, Any]]:
    """Validate the ``__custom__`` payload as string -> JSON value.

    Returns the cleaned dict (None when empty); malformed entries are dropped
    with a warning so a bad payload cannot corrupt the JSONB column.
    """
    if not isinstance(value, dict):
        logger.warning(
            "__custom__ must be a dict, got %s; dropping",
            type(value).__name__,
        )
        return None
    clean_custom: Dict[str, Any] = {}
    for ck, cv in value.items():
        if not isinstance(ck, str):
            logger.warning(
                "__custom__ entry %r must have a string key, dropping",
                ck,
            )
            continue
        clean_value = _clean_custom_json_value(cv)
        if clean_value is _INVALID_CUSTOM_VALUE:
            logger.warning(
                "__custom__ entry %r must contain JSON-compatible values, dropping",
                ck,
            )
            continue
        clean_custom[ck] = clean_value
    return clean_custom or None


def _validate_reasoning_extra_param(key: str, value: Any, logger) -> bool:
    if key == "enable_thinking":
        if isinstance(value, bool):
            return True
        logger.warning(
            "Dropped invalid enable_thinking value %r; expected a boolean",
            value,
        )
        return False
    if key == "reasoning_effort" and value not in REASONING_EFFORT_VALUES:
        logger.warning(
            "Dropped invalid reasoning_effort value %r; expected one of %s",
            value,
            sorted(REASONING_EFFORT_VALUES),
        )
        return False
    if key == "reasoning_budget_tokens":
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return True
        logger.warning(
            "Dropped invalid reasoning_budget_tokens value %r; expected a positive integer",
            value,
        )
        return False
    return True


def _prepare_custom_extra_param(
    value: Any, logger
) -> tuple[Optional[Dict[str, Any]], bool]:
    if not isinstance(value, dict):
        logger.warning(
            "__custom__ must be a dict, got %s; dropping",
            type(value).__name__,
        )
        return None, False
    return _clean_custom_params(value, logger), True


def filter_extra_params(
    model_type: str, extra_params: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Filter extra_params to only keep keys allowed for the given model type.

    Logs a warning for any disallowed keys. Returns None if the result is empty.

    The reserved key ``__custom__`` is always allowed through: it carries
    user-defined key/value pairs edited in the advanced-settings UI. It is
    validated to be a dict of string -> JSON-compatible value; anything else
    is dropped with a warning so a malformed payload cannot corrupt the JSONB
    column. Nested objects and arrays are preserved.
    """
    if not extra_params:
        return None
    import logging

    logger = logging.getLogger(__name__)

    allowed = set(get_extra_param_keys_for_type(model_type))
    filtered = {}
    dropped = []
    for key, value in extra_params.items():
        if key == "__custom__":
            clean_custom, accepted = _prepare_custom_extra_param(value, logger)
            if not accepted:
                dropped.append(key)
                continue
            if clean_custom is not None:
                filtered["__custom__"] = clean_custom
            continue
        if key not in allowed or not _validate_reasoning_extra_param(
            key, value, logger
        ):
            dropped.append(key)
            continue
        filtered[key] = value
    if dropped:
        logger.warning(
            "Dropped extra_params keys not in fixed field set for model_type=%s: %s",
            model_type,
            dropped,
        )
    return filtered if filtered else None


# =============================================================================
# v2.6.0: Model type inference from model name (for custom provider discovery)
# =============================================================================


def _name_matches(name: str, final_segment: str, *prefixes: str) -> bool:
    """True when the full name or its final path segment starts with any prefix."""
    return name.startswith(prefixes) or final_segment.startswith(prefixes)


def _name_contains_any(name: str, final_segment: str, *tokens: str) -> bool:
    """True when any token is a substring of the full name or its final path segment."""
    return any(tok in name or tok in final_segment for tok in tokens)


def _infer_visual_model_type(name: str, final_segment: str) -> Optional[str]:
    """Classify the multimodal families from a lower-cased model name.

    Returns "vlm3" / "vlm2" / "vlm" or None when the name does not look
    multimodal. Evaluation order matters:
    - Video understanding (vlm3) — keywords aligned with develop's TokenPony
      provider classification (TOKENPONY_VIDEO_UNDERSTANDING_KEYWORDS).
    - Image generation (vlm2) — keywords aligned with develop's TokenPony
      provider classification (TOKENPONY_IMAGE_GENERATION_KEYWORDS): catches
      Tongyi-MAI/Z-Image-Turbo, baidu/ERNIE-Image-Turbo, flux/sdxl/wanx/
      seedream/ideogram/recraft families. Checked BEFORE image understanding
      because develop's classifier gives generation keywords priority.
    - Image understanding (vlm) — keywords aligned with develop's TokenPony
      provider (TOKENPONY_IMAGE_UNDERSTANDING_KEYWORDS) plus the legacy
      prefix rules: qwen-vl-*, glm-v*, internvl-*, llava-*, gpt-4o-*.
      "vl" as a standalone dash-segment covers Qwen/Qwen3-VL-* naming.
    """
    if _name_contains_any(name, final_segment, "omni", "video"):
        return "vlm3"
    if _name_contains_any(
        name,
        final_segment,
        "image",
        "dall",
        "flux",
        "stable-diffusion",
        "sdxl",
        "midjourney",
        "wanx",
        "kolors",
        "seedream",
        "ideogram",
        "recraft",
    ):
        return "vlm2"
    if (
        _name_matches(name, final_segment, "qwen-vl-", "internvl-", "llava-", "gpt-4o-", "gpt-4-vision-")
        or re.match(r"^glm[-_]\d+(?:[._-]\d+)?v(?:$|[-_])", final_segment)
        or "vl" in final_segment.split("-")
        or _name_contains_any(name, final_segment, "vision", "visual", "ocr")
    ):
        return "vlm"
    return None


def _infer_model_type_from_name(model_name: str) -> str:
    """Infer a model's type from its name prefix.

    Used when ProviderModelRequest.model_type is None (custom provider discovery
    via OpenAI-compatible /v1/models). Preset providers do not need this because
    their types come from the catalog.

    Matching runs against BOTH the full name and its final path segment so that
    repo-prefixed ids from aggregators (SiliconFlow "BAAI/bge-m3", OpenRouter
    "deepseek/deepseek-v4-flash", "Pro/..." tiers) classify the same as their
    bare names.

    Mapping rules (see design doc Phase 2.6):
    - gpt-* / o1-* / o3-* / o4-* / claude-* / glm-* / qwen-* (non-vl) /
      deepseek-* / llama-* / mistral-* / yi-* / moonshot-* / gemini-* → llm
    - qwen-vl-* / glm-v* / internvl-* / llava-* → vlm
    - text-embedding-* / embedding-* / bge-* (non-reranker) → embedding
    - rerank-* / bge-reranker-* / jina-reranker-* → rerank
    - whisper-* / paraformer-* / sensevoice-* → stt
    - tts-* / cosyvoice-* / speech-* → tts
    - other unmatched → llm (default; user can manually correct in UI)
    """
    if not model_name:
        return "llm"
    name = model_name.lower()
    # Final path segment (after the last "/"): "BAAI/bge-m3" -> "bge-m3",
    # "Pro/deepseek-ai/DeepSeek-V3" -> "deepseek-v3". Checked alongside the
    # full name so repo prefixes on aggregators don't break prefix rules.
    final_segment = name.rsplit("/", 1)[-1]

    # Embedding (check before generic patterns). Besides prefix rules, also
    # match names that merely CONTAIN "embedding" — covers Qwen3-Embedding-*,
    # text-embedding-* variants and similar mid-name conventions on
    # aggregators. "reranker" wins over "embedding" when both appear
    # (bge-reranker-v2-m3 style names).
    if not _name_contains_any(name, final_segment, "reranker") and (
        _name_matches(name, final_segment, "text-embedding-", "embedding-", "bge-")
        or _name_contains_any(name, final_segment, "embedding")
    ):
        return "embedding"
    # Rerank. Also catch names containing "rerank" (Qwen3-Reranker-0.6B style);
    # any name containing "reranker" also contains "rerank", so one token covers both.
    if _name_matches(
        name, final_segment, "rerank-", "bge-reranker-", "jina-reranker-"
    ) or _name_contains_any(name, final_segment, "rerank"):
        return "rerank"
    # STT. Also catch "sensevoice" mid-name (FunAudioLLM/SenseVoiceSmall).
    if _name_matches(
        name, final_segment, "whisper-", "paraformer-", "sensevoice-"
    ) or _name_contains_any(name, final_segment, "sensevoice"):
        return "stt"
    # TTS. Also catch "tts" / "cosyvoice" mid-name (IndexTeam/IndexTTS-2,
    # FunAudioLLM/CosyVoice2-0.5B style aggregator names).
    if _name_matches(
        name, final_segment, "tts-", "cosyvoice-", "speech-"
    ) or _name_contains_any(name, final_segment, "cosyvoice"):
        return "tts"

    visual = _infer_visual_model_type(name, final_segment)
    if visual:
        return visual
    # LLM prefixes and the fallback both resolve to "llm" — unmatched names
    # default to llm so the user can manually correct the type in the UI.
    return "llm"


class ModelConnectStatusEnum(Enum):
    """Enum class for model connection status"""

    NOT_DETECTED = "not_detected"
    DETECTING = "detecting"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"

    @classmethod
    def get_default(cls) -> str:
        """Get default value"""
        return cls.NOT_DETECTED.value

    @classmethod
    def get_value(cls, status: Optional[str]) -> str:
        """Get value based on status, return default value if empty"""
        if not status or status == "":
            return cls.NOT_DETECTED.value
        return status


class ProviderEnum(str, Enum):
    """Supported model providers"""

    SILICON = "silicon"
    OPENAI = "openai"
    MODELENGINE = "modelengine"
    DASHSCOPE = "dashscope"
    TOKENPONY = "tokenpony"
