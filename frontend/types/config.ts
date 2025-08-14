// 重构：状态可以整合
// 模型状态类型
export type ModelStatus = "unchecked" | "available" | "unavailable" | "skippable"

// 模型连接状态类型
export type ModelConnectStatus = "not_detected" | "detecting" | "available" | "unavailable"

// 模型来源类型
export type ModelSource = "openai" | "custom" | "silicon" | "OpenAI-API-Compatible"

// 模型类型
export type ModelType = "llm" | "embedding" | "rerank" | "stt" | "tts" | "vlm" | "multi_embedding"

// 配置存储键名
export const APP_CONFIG_KEY = 'app';
export const MODEL_CONFIG_KEY = 'model';

// 默认配置
export const defaultConfig: GlobalConfig = {
  app: {
    appName: "",
    appDescription: "",
    iconType: "preset",
    customIconUrl: "",
    avatarUri: ""
  },
  models: {
    llm: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: ""
      }
    },
    llmSecondary: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: ""
      }
    },
    embedding: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: "",
      },
      dimension: 0
    },
    multiEmbedding: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: "",
      },
      dimension: 0
    },
    rerank: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: ""
      }
    },
    vlm: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: ""
      }
    },
    stt: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: ""
      }
    },
    tts: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: ""
      }
    }
  }
};

// 模型选项接口
export interface ModelOption {
  id: string
  name: string
  type: ModelType
  maxTokens: number
  source: ModelSource
  apiKey: string
  apiUrl: string
  displayName: string
  connect_status?: ModelConnectStatus
}

// 应用配置接口
export interface AppConfig {
  appName: string
  appDescription: string
  iconType: "preset" | "custom"
  customIconUrl: string | null
  avatarUri: string | null
}

// 重构：整合一下
// 模型API配置接口
export interface ModelApiConfig {
  apiKey: string
  modelUrl: string
}

// 单个模型配置接口
export interface SingleModelConfig {
  modelName: string
  displayName: string
  apiConfig: ModelApiConfig
  dimension?: number  // 只用于 embedding 和 multiEmbedding 模型
}

// 模型配置接口
export interface ModelConfig {
  llm: SingleModelConfig
  llmSecondary: SingleModelConfig
  embedding: SingleModelConfig
  multiEmbedding: SingleModelConfig
  rerank: SingleModelConfig
  vlm: SingleModelConfig
  stt: SingleModelConfig
  tts: SingleModelConfig
}

// 全局配置接口
export interface GlobalConfig {
  app: AppConfig
  models: ModelConfig
}

// Add the type for model validation response with error_code
export interface ModelValidationResponse {
  connectivity: boolean;
  message?: string;
  error_code?: string;
  error_details?: string;
  model_name?: string;
  connect_status: string;
} 
