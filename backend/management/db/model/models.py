# Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

from sqlalchemy import (
    text,
    Boolean,
    Column,
    Float,
    Integer,
    Sequence,
    String,
)


from sqlalchemy.dialects.postgresql import JSONB


from management.db.base import SCHEMA, TableBase


class ModelRecord(TableBase):
    """
    Model list defined by the user on the configuration page
    """
    __tablename__ = "model_record_t"
    __table_args__ = {"schema": SCHEMA}

    model_id = Column(Integer, Sequence("model_record_t_model_id_seq", schema=SCHEMA),
                      primary_key=True, nullable=False, doc="Model ID, unique primary key")
    model_repo = Column(String(100), doc="Model path address")
    model_name = Column(String(100), nullable=False, doc="Model name")
    model_factory = Column(String(
        100), doc="Model vendor, determining the API key and the specific format of the model response. Currently defaults to OpenAI-API-Compatible.")
    model_type = Column(
        String(100), doc="Model type, such as chat, embedding, rerank, tts, asr")
    api_key = Column(
        String(500), doc="Model API key, used for authentication for some models")
    http_headers = Column(JSONB, nullable=False, server_default="{}",
                          comment="Credential-bearing custom HTTP headers, excluded from public responses and snapshots.")
    base_url = Column(
        String(500), doc="Base URL address for requesting remote model services")
    max_tokens = Column(Integer, doc="Maximum available tokens of the model")
    used_token = Column(
        Integer, doc="Number of tokens already used by the model in Q&A")
    display_name = Column(String(
        100), doc="Model name directly displayed on the frontend, customized by the user")
    connect_status = Column(String(
        100), doc="Model connectivity status of the latest detection. Optional values: Detecting, Available, Unavailable")
    tenant_id = Column(String(100), doc="Tenant ID for filtering")
    expected_chunk_size = Column(
        Integer, doc="Expected chunk size for embedding models, used during document chunking")
    maximum_chunk_size = Column(
        Integer, doc="Maximum chunk size for embedding models, used during document chunking")
    ssl_verify = Column(
        Boolean, default=True, doc="Whether to verify SSL certificates when connecting to this model API. Default is true. Set to false for local services without SSL support.")
    chunk_batch = Column(
        Integer, doc="Batch size for concurrent embedding requests during document chunking")
    model_appid = Column(
        String(100), doc="Application ID for model authentication (used by some STT/TTS providers like Volcano Engine)")
    access_token = Column(
        String(100), doc="Access token for model authentication (used by some STT/TTS providers like Volcano Engine)")
    timeout_seconds = Column(
        Integer, doc="Request timeout in seconds for this model. Default is 120 seconds.")
    concurrency_limit = Column(
        Integer, doc="Maximum concurrent requests for this model. Default is null (unlimited).")
    context_window_tokens = Column(
        Integer, doc="Total combined input/output context window in tokens, when the provider uses a combined window. Nullable.")
    max_input_tokens = Column(
        Integer, doc="Provider hard input-token limit when distinct from the combined window. Nullable.")
    max_output_tokens = Column(
        Integer, doc="Provider-supported or operator-configured completion-output cap. Replaces the ambiguous LLM meaning of max_tokens. Nullable.")
    default_output_reserve_tokens = Column(
        Integer, doc="Default output allowance reserved per request before constructing input context. Nullable.")
    tokenizer_family = Column(
        String(100), doc="Token-counting strategy or provider/model tokenizer identifier mapped via tokenizer_registry. Nullable.")
    capacity_source = Column(
        String(100), doc="Source of the persisted capacity value. Optional values: operator, profile, provider_candidate, legacy, default, unknown.")
    capability_profile_version = Column(
        String(100), doc="Version of the approved provider/model capability profile used by the request, e.g. openai/gpt-4o@1.")
    # v2.6.0 inference params (model-level defaults). Nullable; NULL means provider default.
    temperature = Column(
        Float, doc="Default sampling temperature for LLM/VLM models. NULL means provider default. Nullable.")
    top_p = Column(
        Float, doc="Default nucleus sampling probability for LLM/VLM models. NULL means provider default. Nullable.")
    extra_params = Column(
        JSONB, doc="Fixed inference params without dedicated columns (key-value pairs constrained by FIXED_INFERENCE_FIELDS_BY_TYPE). NULL means no extra params.")

    # Schema extension only: NULL capability values remain unknown until outlet migration.
    reasoning_supported = Column(Boolean, comment="Reasoning support: true supported, false unsupported, NULL unknown.")
    reasoning_controls = Column(JSONB, comment="Declared reasoning control domains; NULL unknown, empty array no controls.")
    native_tool_call_supported = Column(Boolean, comment="Native tool call support; NULL unknown, not an execution guarantee.")
    structured_output_supported = Column(Boolean, comment="Structured output support; NULL unknown, formats require binding.")
    temperature_supported = Column(Boolean, comment="Temperature control support; NULL unknown, separate from parameter value.")
    top_p_supported = Column(Boolean, comment="Top-p control support; NULL unknown, separate from parameter value.")
    input_modalities = Column(JSONB, comment="Unique supported input modality names; NULL unknown, empty array no modalities.")
    output_modalities = Column(JSONB, comment="Unique supported output modality names; NULL unknown, empty array no modalities.")
    enable_thinking = Column(Boolean, comment="Saved thinking switch; NULL omitted unless marked as explicit JSON null.")
    default_max_output_tokens = Column(Integer, comment="Saved LLM request output default; separate from the hard output cap. NULL omitted unless explicitly marked null.")
    reasoning_effort = Column(String(30), comment="Saved reasoning effort; NULL omitted unless marked as explicit JSON null.")
    reasoning_budget_tokens = Column(Integer, comment="Saved reasoning token budget; sentinel values require explicit declaration.")
    protocol_id = Column(String(30), comment="Registered model protocol; NULL only before resolved outlet migration completes.")
    resolved_profile = Column(JSONB, comment="Remaining resolved rules, bindings and provenance; no copies of dedicated column values.")
    profile_schema_version = Column(Integer, comment="Persisted resolved profile schema version; NULL for pre-migration rows.")
    config_revision = Column(Integer, nullable=False, default=1, server_default=text("1"),
                             comment="Outlet configuration revision for optimistic updates; initial value 1.")
