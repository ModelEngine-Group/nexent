// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Copied catalog entries are references, not a formal supported-model list. */
export interface AtomicProfileSummary {
  key: string;
  name: string;
  revision: string;
  catalog_kind: "model" | "provider";
  qualification: "reference_only";
  family?: string | null;
  endpoint_hints?: string[];
  suggested_base_url?: string;
  configuration?: Pick<
    ModelProfileDraftResponse,
    "capabilities" | "field_specs" | "parameter_values"
  >;
}

export interface ProfileListRequest {
  query?: string;
  family?: string;
  page?: number;
  page_size?: number;
}

export interface ProfileListResponse {
  catalog_revision: string;
  items: AtomicProfileSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface ProfileProtocolReference {
  ref: string;
  version: number;
}

export interface ProfileProtocolsResponse {
  items: ProfileProtocolReference[];
  authentication_schemes: ProfileProtocolReference[];
}

export interface ModelProfileSelection {
  key: string;
  revision: string;
}

export interface ModelProfileProviderInfo {
  base_url: string;
  provider_id?: string | null;
  ssl_verify?: boolean;
  timeout_seconds?: number;
  concurrency_limit?: number | null;
}

export type ThinkingDegreeMode = "default" | "effort" | "budget_tokens";

export type ThinkingControlFormat =
  "profile_default" | "enable_thinking" | "thinking_type" | "chat_template";

export interface ModelProfileDraftRequest {
  thinking_control?: ThinkingControlFormat;
  thinking_mode?: ThinkingDegreeMode;
  selection_mode?: "auto" | "manual";
  model_profile?: ModelProfileSelection | null;
  provider_profile?: ModelProfileSelection | null;
  catalog_revision?: string | null;
  provider_info: ModelProfileProviderInfo;
  request_model_id: string;
  display_name?: string | null;
  protocol_id?: "openai_chat_completions";
  authentication_scheme?: "bearer_token_v1" | "no_auth_v1";
  context_limits?: Partial<ModelOutletProfile["capabilities"]["context"]>;
  context_configuration?: {
    output_reserve_tokens?: number | null;
    tokenizer_family?: string | null;
  };
  parameter_values?: Record<string, unknown>;
  extra_api_parameters?: Array<{ path: string; value: unknown }>;
}

export interface ModelParameterRule {
  key: string;
  schema: Record<string, unknown>;
  visible: boolean;
  editable: boolean;
  required: boolean;
  allowed_scopes: Array<"outlet" | "conversation">;
  ui_group: string;
  default_value?: unknown;
  fixed_value?: unknown;
  condition?: Record<string, unknown> | null;
}

export interface ModelProfileDraftResponse {
  catalog_revision: string;
  candidates: { models: string[]; providers: string[] };
  selected: { model: string | null; provider: string | null };
  field_specs: ModelParameterRule[];
  parameter_values: Record<string, unknown>;
  capabilities: Record<string, unknown>;
  instruction_mapping: Record<string, unknown>;
  conflicts: Array<{ category: string; field: string }>;
}

export interface ModelOutletCreateRequest extends ModelProfileDraftRequest {
  api_key?: string | null;
}

export interface ModelOutletProfile {
  provenance?: {
    provider_metadata?: {
      operator_thinking?: { preset?: ThinkingControlFormat };
      operator_thinking_degree?: { mode?: ThinkingDegreeMode };
      [key: string]: unknown;
    };
  };
  identity: {
    display_name: string;
    request_model_id: string;
    provider_id: string;
  };
  connection: {
    base_url: string;
    ssl_verify: boolean;
    timeout_seconds: number;
    concurrency_limit: number | null;
  };
  capabilities: {
    sampling?: {
      top_p?: { status: "supported" | "unsupported" | "unknown" };
    };
    context: {
      combined_window: number | null;
      input_limit: number | null;
      output_limit: number | null;
    };
  };
  context_configuration: {
    output_reserve_tokens: number | null;
    tokenizer_family: string | null;
    capacity_source: string | null;
    capability_profile_version: string | null;
  };
  parameter_values: Record<string, unknown>;
  parameter_rules: ModelParameterRule[];
  extra_api_parameters: Array<{ path: string; value: unknown }>;
  [key: string]: unknown;
}

export interface ModelOutletResponse {
  model_id: number;
  config_revision: number;
  has_credential: boolean;
  profile: ModelOutletProfile;
  field_specs?: ModelParameterRule[];
}

/** Omission preserves a value; delete_parameters explicitly removes it. */
export interface ModelOutletPatchRequest {
  thinking_control?: ThinkingControlFormat;
  thinking_mode?: ThinkingDegreeMode;
  expected_revision: number;
  parameter_values?: Record<string, unknown>;
  delete_parameters?: string[];
  connection?: Partial<ModelOutletProfile["connection"]>;
  display_name?: string;
  context_limits?: Partial<ModelOutletProfile["capabilities"]["context"]>;
  context_configuration?: Partial<ModelOutletProfile["context_configuration"]>;
  api_key?: string | null;
  extra_api_parameters?: Array<{ path: string; value: unknown }>;
}

export type ModelOutletValidationRequest =
  | { outlet_id: number; expected_revision?: number; draft?: never }
  | {
      draft: ModelOutletCreateRequest;
      outlet_id?: never;
      expected_revision?: never;
    };

export interface ModelOutletValidationResponse {
  ok: boolean;
  error: { category: string; message?: string } | null;
  check_scope: "connection_only";
  model_id: number | null;
  config_revision: number;
}

export interface ConversationModelPreferenceView {
  output_limit?: number | null;
  version: number;
  config_revision: number;
  parameter_values: Record<string, unknown>;
  defaults: Record<string, unknown>;
  field_specs: ModelParameterRule[];
  issues: Array<{ category: string; field: string }>;
}
