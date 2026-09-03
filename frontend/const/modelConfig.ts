import { publicAsset } from "@/lib/publicAsset";

export const APP_DISPLAY_NAME = "Nexent";
export const APP_DISPLAY_DESCRIPTION =
  "Nexent 是一个开源智能体平台，基于 MCP 工具生态系统，提供灵活的多模态问答、检索、数据分析、处理等能力。";

// Model type constants
export const MODEL_TYPES = {
  LLM: "llm",
  EMBEDDING: "embedding",
  MULTI_EMBEDDING: "multi_embedding",
  RERANK: "rerank",
  STT: "stt",
  TTS: "tts",
  VLM: "vlm",
  VLM2: "vlm2",
  VLM3: "vlm3",
  VLM4: "vlm4",
} as const;

// Model source constants
export const MODEL_SOURCES = {
  OPENAI: "openai",
  SILICON: "silicon",
  MODELENGINE: "modelengine",
  OPENAI_API_COMPATIBLE: "OpenAI-API-Compatible",
  CUSTOM: "custom",
  DASHSCOPE: "dashscope",
  TOKENPONY: "tokenpony",
  VOLCENGINE: "volcengine",
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
  "modelengine",
  "qwen",
  "openai",
  "siliconflow",
  "jina",
  "deepseek",
  "aliyuncs",
  "tokenpony",
  "dashscope",
  "volcengine",
] as const;

export type ModelProviderKey = (typeof MODEL_PROVIDER_KEYS)[number];

// Direct provider hint string mapping (no arrays)
export const PROVIDER_HINTS: Record<ModelProviderKey, string> = {
  modelengine: "open/router",
  qwen: "qwen",
  openai: "openai",
  siliconflow: "siliconflow",
  jina: "jina",
  deepseek: "deepseek",
  aliyuncs: "aliyuncs",
  tokenpony: "tokenpony",
  dashscope: "dashscope",
  volcengine: "bytedance",
};

// Icon filenames for providers
export const PROVIDER_ICON_MAP: Record<ModelProviderKey, string> = {
  modelengine: publicAsset("/modelengine-logo.png"),
  qwen: publicAsset("/qwen.png"),
  openai: publicAsset("/openai.png"),
  siliconflow: publicAsset("/siliconflow.png"),
  jina: publicAsset("/jina.png"),
  deepseek: publicAsset("/deepseek.png"),
  aliyuncs: publicAsset("/aliyuncs.png"),
  dashscope: publicAsset("/aliyuncs.png"),
  tokenpony: publicAsset("/tokenpony.png"),
  volcengine: publicAsset("/volcengine.png"),
};

export const OFFICIAL_PROVIDER_ICON = publicAsset("/modelengine-logo.png");
export const DEFAULT_PROVIDER_ICON = publicAsset("/default-icon.png");

// Provider official website links
export const PROVIDER_LINKS: Record<string, string> = {
  modelengine: "https://modelengine-ai.net/",
  siliconflow: "https://siliconflow.ai/",
  openai: "https://platform.openai.com/",
  kimi: "https://platform.moonshot.ai/",
  deepseek: "https://platform.deepseek.com/",
  qwen: "https://bailian.console.aliyun.com/",
  jina: "https://jina.ai/",
  baai: "https://www.baai.ac.cn/",
  dashscope: "https://dashscope.aliyun.com/",
  tokenpony: "https://www.tokenpony.cn/",
  volcengine: "https://www.volcengine.com/",
};

// User role constants
export const USER_ROLES = {
  SPEED: "SPEED",
  SU: "SU",
  ADMIN: "ADMIN",
  DEV: "DEV",
  USER: "USER",
  ASSET_OWNER: "ASSET_OWNER",
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
