// Model connection status type
export type ModelConnectStatus =
  "not_detected" | "detecting" | "available" | "unavailable";

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
  | "vlm4"
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
  capacityFieldMetadata?: CapacityFieldMetadata | null;
  canonicalModelId?: string | null;
  modelIdentityMetadata?: ModelIdentityMetadata | null;
  tokenizerMatchMetadata?: ProfileMatchMetadata | null;
  tokenCountProbeMetadata?: TokenCountProbeMetadata | null;
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
  capacityFieldMetadata?: CapacityFieldMetadata | null;
  canonicalModelId?: string | null;
  modelIdentityMetadata?: ModelIdentityMetadata | null;
  tokenizerMatchMetadata?: ProfileMatchMetadata | null;
  tokenCountProbeMetadata?: TokenCountProbeMetadata | null;
}

export type CapacityFieldSource =
  "catalog" | "provider" | "operator" | "legacy" | "unknown";

export interface CapacityFieldProvenance {
  source: CapacityFieldSource;
  confidence?: "high" | "medium" | "low" | "unknown";
  profileVersion?: string;
  evidenceId?: string;
  verifiedAt?: string;
  updatedAt?: string;
}

export interface CapacityFieldMetadata {
  schemaVersion: number;
  fields: Partial<
    Record<keyof CapacitySuggestionFields, CapacityFieldProvenance>
  >;
}

export interface ModelIdentityMetadata {
  schemaVersion: number;
  canonicalId?: string;
  resolved?: boolean;
  ambiguity?: boolean;
  confidence?: string;
  matcherVersion?: string;
}

export interface ProfileMatchMetadata {
  schemaVersion: number;
  selectedProfile?: string | null;
  confidence?: string | null;
  source: string;
  reason: string;
  matcherVersion: string;
  candidates?: string[];
  autoApplicable?: boolean;
}

export interface TokenCountProbeMetadata {
  schemaVersion: number;
  status:
    | "supported"
    | "unsupported"
    | "authorization_error"
    | "temporarily_unavailable"
    | "invalid_response"
    | "unknown";
  reason: string;
  selectedProtocol?: string | null;
  checkedAt?: string;
  staleAt?: string;
}

export interface CapacitySuggestionFields {
  contextWindowTokens?: number;
  maxInputTokens?: number;
  maxOutputTokens?: number;
  defaultOutputReserveTokens?: number;
  tokenizerFamily?: string;
}

export type CapacitySuggestionMatchKind =
  "catalog_exact" | "catalog_fuzzy" | "provider_discovery" | "none";

export type CapacitySuggestionConfidence = "high" | "medium" | "low";

export interface CapacitySuggestion {
  suggestions?: CapacitySuggestionFields | null;
  matchKind: CapacitySuggestionMatchKind;
  matchConfidence?: CapacitySuggestionConfidence | null;
  matchExplanation: string;
  suggestedProvider?: string | null;
  canonicalModelName?: string | null;
  capabilityProfileVersion?: string | null;
  capacitySourceOnAccept?: "operator" | "profile" | null;
  canonicalIdentity?: ModelIdentityMetadata | null;
  capacityMatch?: ProfileMatchMetadata | null;
  tokenizerMatch?: ProfileMatchMetadata | null;
  governanceMetadataProposal?: CapacityFieldMetadata | null;
}

export interface CapacityAdoptionFieldDiff {
  currentValue?: number | string | null;
  currentSource: CapacityFieldSource;
  proposedValue?: number | string | null;
  proposedSource: "catalog";
  changed: boolean;
  blockedByManual: boolean;
  applicable: boolean;
}

export interface CapacityAdoptionPreview {
  displayName: string;
  canonicalModelId: string;
  matcherVersion: string;
  currentProfileVersion?: string | null;
  proposedProfileVersion: string;
  fields: Record<string, CapacityAdoptionFieldDiff>;
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

export type CapacityHealthStatus =
  | "healthy"
  | "review_due"
  | "expired"
  | "estimated"
  | "unconfigured"
  | "invalid"
  | "probe_degraded";

export interface CapacityHealthItem {
  modelId: number;
  displayName: string;
  modelName: string;
  modelFactory?: string | null;
  modelType: "llm" | "vlm" | "vlm2" | "vlm3";
  status: CapacityHealthStatus;
  reasons: string[];
  action:
    "none" | "edit" | "review_profile" | "review_evidence" | "retry_probe";
  matcherVersion: string;
  profileVersion?: string | null;
  verifiedAt?: string | null;
  reviewAt?: string | null;
  expiresAt?: string | null;
  suggestionAvailable: boolean;
}

export interface CapacityHealth {
  catalogRevision: string;
  generatedAt: string;
  total: number;
  counts: Partial<Record<CapacityHealthStatus, number>>;
  items: CapacityHealthItem[];
}

export interface CapacityCatalogCandidate {
  revision: string;
  sourceIdentity: string;
  stagedAt: string;
  added: string[];
  changed: string[];
  removed: string[];
}

export interface CapacityCatalogStatus {
  activeRevision: string;
  profileCount: number;
  lifecycleCounts: Partial<
    Record<"current" | "review_due" | "expired", number>
  >;
  candidate?: CapacityCatalogCandidate | null;
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
  vlm4: SingleModelConfig;
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
