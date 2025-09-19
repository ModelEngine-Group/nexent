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
  VLM: "vlm"
} as const;

// Model source constants
export const MODEL_SOURCES = {
  OPENAI: "openai",
  SILICON: "silicon",
  OPENAI_API_COMPATIBLE: "OpenAI-API-Compatible",
  CUSTOM: "custom"
} as const;

// Model status constants
export const MODEL_STATUS = {
  AVAILABLE: "available",
  UNAVAILABLE: "unavailable",
  CHECKING: "detecting",
  UNCHECKED: "not_detected"
} as const;

// Icon type constants
export const ICON_TYPES = {
  PRESET: "preset",
  CUSTOM: "custom"
} as const;

// User role constants
export const USER_ROLES = {
  USER: "user",
  ADMIN: "admin"
} as const;

// Memory tab key constants
export const MEMORY_TAB_KEYS = {
  BASE: "base",
  TENANT: "tenant", 
  AGENT_SHARED: "agentShared",
  USER_PERSONAL: "userPersonal",
  USER_AGENT: "userAgent"
} as const;

// Type for memory tab keys
export type MemoryTabKey = (typeof MEMORY_TAB_KEYS)[keyof typeof MEMORY_TAB_KEYS];

// Connection status constants
export const CONNECTION_STATUS = {
  SUCCESS: "success",
  ERROR: "error", 
  PROCESSING: "processing"
} as const;

export type ConnectionStatus = (typeof CONNECTION_STATUS)[keyof typeof CONNECTION_STATUS];

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
