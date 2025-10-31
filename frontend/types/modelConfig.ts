import { CONNECTION_STATUS } from "@/const/modelConfig";

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
  | "OpenAI-API-Compatible";

// Model type
export type ModelType =
  | "llm"
  | "embedding"
  | "rerank"
  | "stt"
  | "tts"
  | "vlm"
  | "multi_embedding";

// Model option interface
export interface ModelOption {
  id: number;
  name: string;
  type: ModelType;
  maxTokens: number;
  source: ModelSource;
  apiKey: string;
  apiUrl: string;
  displayName: string;
  connect_status?: ModelConnectStatus;
  expectedChunkSize?: number;
  maximumChunkSize?: number;
}

// Application configuration interface
export interface AppConfig {
  appName: string;
  appDescription: string;
  iconType: "preset" | "custom";
  customIconUrl: string | null;
  avatarUri: string | null;
}

// Model API configuration interface
export interface ModelApiConfig {
  apiKey: string;
  modelUrl: string;
}

// Single model configuration interface
export interface SingleModelConfig {
  modelName: string;
  displayName: string;
  apiConfig: ModelApiConfig;
  dimension?: number; // Only used for embedding and multiEmbedding models
}

// Model configuration interface
export interface ModelConfig {
  llm: SingleModelConfig;
  embedding: SingleModelConfig;
  multiEmbedding: SingleModelConfig;
  rerank: SingleModelConfig;
  vlm: SingleModelConfig;
  stt: SingleModelConfig;
  tts: SingleModelConfig;
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
  error?: string;  // Error message when connectivity fails
}

// Model engine check result interface
export interface ModelEngineCheckResult {
  status:
    | typeof CONNECTION_STATUS.SUCCESS
    | typeof CONNECTION_STATUS.ERROR
    | typeof CONNECTION_STATUS.PROCESSING;
  lastChecked: string;
}
