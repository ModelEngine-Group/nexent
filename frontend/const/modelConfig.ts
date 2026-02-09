import { GlobalConfig } from "../types/modelConfig";

// Configuration storage key name
export const APP_CONFIG_KEY = "app";
export const MODEL_CONFIG_KEY = "model";

// Model type constants
export const MODEL_TYPES = {
  LLM: "llm",
  EMBEDDING: "embedding",
  MULTI_EMBEDDING: "multi_embedding",
  RERANK: "rerank",
  STT: "stt",
  TTS: "tts",
  VLM: "vlm",
} as const;

// Model source constants
export const MODEL_SOURCES = {
  OPENAI: "openai",
  SILICON: "silicon",
  MODELENGINE: "modelengine",
  OPENAI_API_COMPATIBLE: "OpenAI-API-Compatible",
  CUSTOM: "custom",
} as const;

// Model status constants
export const MODEL_STATUS = {
  AVAILABLE: "available",
  UNAVAILABLE: "unavailable",
  CHECKING: "detecting",
  UNCHECKED: "not_detected",
} as const;

// Icon type constants
export const ICON_TYPES = {
  PRESET: "preset",
  CUSTOM: "custom",
} as const;

// Provider detection and icon mapping
export const MODEL_PROVIDER_KEYS = [
  "qwen",
  "openai",
  "siliconflow",
  "jina",
  "deepseek",
  "aliyuncs",
] as const;

export type ModelProviderKey = (typeof MODEL_PROVIDER_KEYS)[number];

// Direct provider hint string mapping (no arrays)
export const PROVIDER_HINTS: Record<ModelProviderKey, string> = {
  qwen: "qwen",
  openai: "openai",
  siliconflow: "siliconflow",
  jina: "jina",
  deepseek: "deepseek",
  aliyuncs: "aliyuncs",
};

// Icon filenames for providers
export const PROVIDER_ICON_MAP: Record<ModelProviderKey, string> = {
  qwen: "/qwen.png",
  openai: "/openai.png",
  siliconflow: "/siliconflow.png",
  jina: "/jina.png",
  deepseek: "/deepseek.png",
  aliyuncs: "/aliyuncs.png",
};

export const OFFICIAL_PROVIDER_ICON = "/modelengine-logo.png";
export const DEFAULT_PROVIDER_ICON = "/default-icon.png";

// Provider official website links
export const PROVIDER_LINKS: Record<string, string> = {
  modelengine: "https://modelengine-ai.net/",
  siliconflow: "https://siliconflow.ai/",
  openai: "https://platform.openai.com/",
  kimi: "https://platform.moonshot.ai/",
  deepseek: "https://platform.deepseek.com/",
  qwen: "https://bailian.console.aliyun.com/",
  jina: "https://jina.ai/",
  baai: "https://www.baai.ac.cn/"
};

// User role constants
export const USER_ROLES = {
  SPEED: "SPEED",
  SU: "SU",
  ADMIN: "ADMIN",
  DEV: "DEV",
  USER: "USER",
} as const;

// Memory tab key constants
export const MEMORY_TAB_KEYS = {
  BASE: "base",
  TENANT: "tenant",
  AGENT_SHARED: "agentShared",
  USER_PERSONAL: "userPersonal",
  USER_AGENT: "userAgent",
} as const;

// Type for memory tab keys
export type MemoryTabKey =
  (typeof MEMORY_TAB_KEYS)[keyof typeof MEMORY_TAB_KEYS];

// Layout configuration constants
export const LAYOUT_CONFIG = {
  CARD_HEADER_PADDING: "10px 24px",
  CARD_BODY_PADDING: "12px 20px",
  MODEL_TITLE_MARGIN_LEFT: "0px",
  HEADER_HEIGHT: 57, // Card title height
  BUTTON_AREA_HEIGHT: 48, // Button area height
  CARD_GAP: 12, // Row gutter
  // App config specific
  APP_CARD_BODY_PADDING: "8px 20px",
};

// Card theme constants
export const CARD_THEMES = {
  default: {
    borderColor: "#e6e6e6",
    backgroundColor: "#ffffff",
  },
  llm: {
    borderColor: "#e6e6e6",
    backgroundColor: "#ffffff",
  },
  embedding: {
    borderColor: "#e6e6e6",
    backgroundColor: "#ffffff",
  },
  reranker: {
    borderColor: "#e6e6e6",
    backgroundColor: "#ffffff",
  },
  multimodal: {
    borderColor: "#e6e6e6",
    backgroundColor: "#ffffff",
  },
  voice: {
    borderColor: "#e6e6e6",
    backgroundColor: "#ffffff",
  },
};

// Default configuration
export const defaultConfig: GlobalConfig = {
  app: {
    appName: "",
    appDescription: "",
    iconType: ICON_TYPES.PRESET,
    customIconUrl: "",
    avatarUri: "",
    modelEngineEnabled: false,
    datamateUrl: "",
  },
  models: {
    llm: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: "",
      },
    },
    embedding: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: "",
      },
      dimension: 0,
    },
    multiEmbedding: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: "",
      },
      dimension: 0,
    },
    rerank: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: "",
      },
    },
    vlm: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: "",
      },
    },
    stt: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: "",
      },
    },
    tts: {
      modelName: "",
      displayName: "",
      apiConfig: {
        apiKey: "",
        modelUrl: "",
      },
    },
  },
};
