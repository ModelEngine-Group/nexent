// Model connection status type
export type ModelConnectStatus =
  | "not_detected"
  | "detecting"
  | "available"
  | "unavailable";

// API response type
export interface ApiResponse<T = any> {
  code: number;
  message?: string;
  data?: T;
}

// Model source type
export type ModelSource =
  | "openai"
  | "custom"
  | "silicon"
  | "dashscope"
  | "tokenpony"
  | "OpenAI-API-Compatible"
  | "modelengine"
  | "volcengine";

// Model type
export type ModelType =
  | "llm"
  | "embedding"
  | "rerank"
  | "stt"
  | "tts"
  | "vlm"
  | "vlm2"
  | "vlm3"
  | "multi_embedding";

// Model option interface
export interface ModelOption {
  id: number;
  name: string;
  type: ModelType;
  maxTokens: number;
  contextWindowTokens?: number;
  maxInputTokens?: number;
  maxOutputTokens?: number;
  defaultOutputReserveTokens?: number;
  tokenizerFamily?: string;
  capacitySource?: string;
  capabilityProfileVersion?: string;
  source: ModelSource;
  apiKey: string;
  apiUrl: string;
  displayName: string;
  connect_status?: ModelConnectStatus;
  expectedChunkSize?: number;
  maximumChunkSize?: number;
  chunkingBatchSize?: number;
  // STT/TTS specific fields
  modelFactory?: string;
  modelAppid?: string;
  accessToken?: string;
  timeoutSeconds?: number;
  concurrencyLimit?: number;
  // v2.6.0 inference params (model-level defaults)
  temperature?: number;
  topP?: number;
  extraParams?: Record<string, unknown>;
}

// Application configuration interface
export interface AppConfig {
  appName: string;
  appDescription: string;
  iconType: "preset" | "custom";
  iconKey: string; // Selected preset icon key
  customIconUrl: string | null;
  avatarUri: string | null;
  modelEngineEnabled: boolean;
  datamateUrl: string | null;
}

// Model API configuration interface
export interface ModelApiConfig {
  apiKey: string;
  modelUrl: string;
}

// STT model specific configuration interface
export interface STTModelConfig extends SingleModelConfig {
  modelFactory?: string; // Model factory (e.g., "volcengine", "dashscope")
  modelAppid?: string; // App ID for Volcano STT
  accessToken?: string; // Access token for Volcano STT
}

// TTS model specific configuration interface
export interface TTSModelConfig extends SingleModelConfig {
  modelFactory?: string; // Model factory (e.g., "volcengine", "dashscope")
  modelAppid?: string; // App ID for Volcano TTS
  accessToken?: string; // Access token for Volcano TTS
}

// Single model configuration interface
export interface SingleModelConfig {
  id?: number;
  modelName: string;
  displayName: string;
  apiConfig: ModelApiConfig;
  dimension?: number; // Only used for embedding and multiEmbedding models
  contextWindowTokens?: number;
  maxInputTokens?: number;
  maxOutputTokens?: number;
  defaultOutputReserveTokens?: number;
  tokenizerFamily?: string;
  capacitySource?: string;
  capabilityProfileVersion?: string;
}

export interface CapacitySuggestionFields {
  contextWindowTokens?: number;
  maxInputTokens?: number;
  maxOutputTokens?: number;
  defaultOutputReserveTokens?: number;
  tokenizerFamily?: string;
}

export type CapacitySuggestionMatchKind =
  | "catalog_exact"
  | "catalog_fuzzy"
  | "provider_discovery"
  | "none";

export type CapacitySuggestionConfidence = "high" | "medium" | "low";

export interface CapacitySuggestion {
  suggestions?: CapacitySuggestionFields | null;
  matchKind: CapacitySuggestionMatchKind;
  matchConfidence?: CapacitySuggestionConfidence | null;
  matchExplanation: string;
  suggestedProvider?: string | null;
  canonicalModelName?: string | null;
  capabilityProfileVersion?: string | null;
  capacitySourceOnAccept?: "operator" | null;
}

export interface CapacityCoverageBareModel {
  modelId: number;
  modelName: string;
  modelFactory?: string | null;
  modelType: "llm" | "vlm" | "vlm2" | "vlm3";
  maxTokens?: number | null;
  suggestionAvailable: boolean;
}

export interface CapacityCoverage {
  totalLlmVlm: number;
  bareCount: number;
  bareModels: CapacityCoverageBareModel[];
}

// Model configuration interface
export interface ModelConfig {
  llm: SingleModelConfig;
  embedding: SingleModelConfig;
  multiEmbedding: SingleModelConfig;
  rerank: SingleModelConfig;
  vlm: SingleModelConfig;
  vlm2: SingleModelConfig;
  vlm3: SingleModelConfig;
  stt: STTModelConfig;
  tts: TTSModelConfig;
}

// Global configuration interface
export interface GlobalConfig {
  app: AppConfig;
  models: ModelConfig;
}

// Add the type for model validation response with error_code
export interface ModelValidationResponse {
  connectivity: boolean;
  model_name: string;
  error?: string; // Error message when connectivity fails
  capacitySuggestion?: CapacitySuggestion | null;
}

// =============================================================================
// Model Catalog (预置模型目录) types
// =============================================================================

/**
 * Provider summary returned by GET /model/catalog/providers.  One item per
 * provider block in backend/configs/model_catalog.json.
 * Field names align with Pydantic's default (snake_case) JSON dump so no
 * field-level mapping is needed between backend and frontend.
 */
export interface ModelCatalogProviderInfo {
  provider_key: string;         // e.g. "silicon", "dashscope"
  display_name: string;             // human-readable (zh-CN) name for UI buttons
  base_url?: string | null;       // default API base URL for this provider
  supported_model_types: ModelType[]; // llm / embedding / rerank / ...
  model_count?: number;          // how many preset models are registered
  capabilities?: string[];             // e.g. ["support_reasoning", "tool_calls"]
  docs_url?: string | null;
  pricing_url?: string | null;
}

/**
 * A single model profile from the catalog.  Every field is intentionally
 * aligned to the snake_case form the backend /model/create endpoint accepts, so
 * the frontend can do a straight 1:1 spread into the Add Model form.
 *
 * NOTE: extra fields from backend are stored as snake_case since they pass through
 * Pydantic->json. In the frontend we keep them as snake_case too to avoid
 * mapping boilerplate when submitting to /model/create.
 */
export interface ModelCatalogProfile {
  model_type: ModelType;
  display_name?: string | null;
  base_url?: string | null;
  model_factory?: string | null;
  context_window_tokens?: number | null;
  max_input_tokens?: number | null;
  max_output_tokens?: number | null;
  default_output_reserve_tokens?: number | null;
  tokenizer_family?: string | null;
  capability_profile_version?: string | null;
  support_tool_calls?: boolean | null;
  support_structured_outputs?: boolean | null;
  support_reasoning?: boolean | null;
  support_vision?: boolean | null;
  is_multimodal_inputs?: boolean | null;
  modality?: string | null;
  dimension?: number | null;
  max_audio_length_seconds?: number | null;
  audio_sampling_rate?: number | null;
  expected_chunk_size?: number | null;
  maximum_chunk_size?: number | null;
  chunking_batch_size?: number | null;
  timeout_seconds?: number | null;
  concurrency_limit?: number | null;
  recommended?: boolean | null;
  capabilities?: string[];
  tags?: string[];
  pricing_per_1k_input_tokens_usd?: number | null;
  pricing_per_1k_output_tokens_usd?: number | null;
  docs_url?: string | null;
  release_date?: string | null;
}

/** Entry from GET /model/catalog/{provider}/models */
export interface ModelCatalogModelEntry {
  provider_key: string;
  model_name: string;          // e.g. "Qwen/Qwen3-8B" (slash allowed in URL path)
  profile: ModelCatalogProfile;
}

/** Single provider + all its models, used inside the /catalog/all payload. */
export interface ModelCatalogFullProvider {
  provider_info: ModelCatalogProviderInfo;
  models: ModelCatalogModelEntry[];
}

/**
 * Payload returned by GET /model/catalog/all.
 * One call gives the frontend everything it needs - all filtering and
 * individual profile lookups are done in the browser.
 */
export interface ModelCatalogFullPayload {
  version: string;
  metadata?: Record<string, any>;
  providers: ModelCatalogFullProvider[];
}

/** Generic wrapper around catalog endpoint responses all share this envelope. */
export interface ModelCatalogEnvelope<T> {
  message: string;
  catalog_available: boolean;
  data: T;
}

// =============================================================================
// v2.6.0: Fixed inference field specs (advanced settings)
// =============================================================================

/** Field type for fixed inference params, mirrors backend FieldSpec.type */
export type InferenceFieldType =
  | "str"
  | "int"
  | "float"
  | "bool"
  | "select"
  | "array_str";

/** Single field specification, mirrors backend FieldSpec Pydantic model. */
export interface InferenceFieldSpec {
  key: string;
  label: string;
  type: InferenceFieldType;
  range?: number[] | null; // [min, max] for numeric fields
  default?: unknown;
  options?: string[] | null; // for "select" type
  max_items?: number | null; // for "array_str" type
}

/** Field specs grouped by model type, returned by GET /model/catalog/inference_field_specs */
export type InferenceFieldSpecsByType = Record<string, InferenceFieldSpec[]>;

/**
 * Per-agent model params override.
 * Shape: { "<model_id>": { temperature?: number, topP?: number, extraParams?: Record<string, unknown> } }
 */
export type ModelParamsOverride = Record<
  string,
  {
    temperature?: number | null;
    top_p?: number | null;
    extra_params?: Record<string, unknown> | null;
  }
>;
