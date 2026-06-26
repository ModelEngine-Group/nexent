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
