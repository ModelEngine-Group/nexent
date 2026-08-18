// ========== Agent Configuration Constants ==========

import type { LayoutConfig } from "../types/agentConfig";

// Agent call relationship graph theme/colors
export const AGENT_CALL_RELATIONSHIP_THEME_CONFIG = {
  colors: {
    node: {
      main: "#2c3e50",
      levels: {
        1: "#3498db",
        2: "#9b59b6",
        3: "#e74c3c",
        4: "#f39c12",
      },
      tools: {
        1: "#e67e22",
        2: "#1abc9c",
        3: "#34495e",
        4: "#f1c40f",
      },
    },
  },
} as const;

export const AGENT_CALL_RELATIONSHIP_NODE_TYPES = {
  MAIN: "main",
  SUB: "sub",
  TOOL: "tool",
} as const;

export const AGENT_CALL_RELATIONSHIP_ORIENTATION = {
  VERTICAL: "vertical",
  HORIZONTAL: "horizontal",
} as const;

export type AgentCallRelationshipOrientation =
  (typeof AGENT_CALL_RELATIONSHIP_ORIENTATION)[keyof typeof AGENT_CALL_RELATIONSHIP_ORIENTATION];

export const ROLE_ASSISTANT = "assistant" as const;

export const TOOL_SOURCE_TYPES = {
  MCP: "mcp",
  LOCAL: "local",
  LANGCHAIN: "langchain",
  OTHER: "other",
} as const;

export const GENERATE_PROMPT_STREAM_TYPES = {
  DUTY: "duty",
  CONSTRAINT: "constraint",
  FEW_SHOTS: "few_shots",
  AGENT_VAR_NAME: "agent_var_name",
  AGENT_DESCRIPTION: "agent_description",
  AGENT_DISPLAY_NAME: "agent_display_name",
  GREETING_MESSAGE: "greeting_message",
  EXAMPLE_QUESTIONS: "example_questions",
} as const;

export const TOOL_PARAM_TYPES = {
  STRING: "string",
  NUMBER: "number",
  BOOLEAN: "boolean",
  ARRAY: "array",
  OBJECT: "object",
} as const;

export const NAME_CHECK_STATUS = {
  AVAILABLE: "available",
  EXISTS_IN_TENANT: "exists_in_tenant",
  EXISTS_IN_OTHER_TENANT: "exists_in_other_tenant",
  CHECK_FAILED: "check_failed",
} as const;

export type NameCheckStatus =
  (typeof NAME_CHECK_STATUS)[keyof typeof NAME_CHECK_STATUS];

export type ToolSourceType =
  (typeof TOOL_SOURCE_TYPES)[keyof typeof TOOL_SOURCE_TYPES];

export type GeneratePromptStreamType =
  (typeof GENERATE_PROMPT_STREAM_TYPES)[keyof typeof GENERATE_PROMPT_STREAM_TYPES];

// Agent call relationship node default size
export const AGENT_CALL_RELATIONSHIP_NODE_SIZE = {
  width: 140,
  height: 60,
} as const;

// Default layout configuration for Agent Setup pages
export const AGENT_SETUP_LAYOUT_DEFAULT: LayoutConfig = {
  CARD_HEADER_PADDING: "10px 24px",
  CARD_BODY_PADDING: "12px 20px",
  DRAWER_WIDTH: "40%",
};

// Tool parameter enum configurations (defined frontend-side for consistent rendering)
export const TOOL_PARAM_OPTIONS = {
  // Knowledge base search tool
  knowledge_base_search: {
    search_mode: ["hybrid", "accurate", "semantic"],
    multimodal: [true, false],
  },
  // Dify search tool
  dify_search: {
    search_method: [
      "keyword_search",
      "semantic_search",
      "full_text_search",
      "hybrid_search",
    ],
  },
  // DataMate search tool
  datamate_search: {
    // No enum parameters currently defined
  },
  // Haotian search tool
  haotian_search: {
    search_method: [
      "keyword_search",
      "semantic_search",
      "full_text_search",
      "hybrid_search",
    ],
  },
  // AIDP search tool
  aidp_search: {
    search_method: [
      "hybrid_search",
      "vector_search",
      "full_text_search",
    ],
    reranking_mode: ["performance", "high_accuracy"],
    multi_modal: [true, false],
    reranking_enable: [true, false],
    rewrite_enable: [true, false],
    related_search_enable: [true, false],
  },
} as const;

// Numeric value ranges for configurable tool params.
// Mirrors backend TOOL_PARAM_CONSTRAINTS (backend/services/tool_param_validation.py).
export const TOOL_PARAM_RANGES: Record<
  string,
  Record<string, { min: number; max: number; type: "int" | "float" }>
> = {
  knowledge_base_search: { top_k: { min: 1, max: 100, type: "int" } },
  dify_search: { top_k: { min: 1, max: 100, type: "int" } },
  datamate_search: {
    top_k: { min: 1, max: 100, type: "int" },
    threshold: { min: 0, max: 1, type: "float" },
    kb_page: { min: 1, max: 10000, type: "int" },
    kb_page_size: { min: 1, max: 100, type: "int" },
  },
  haotian_search: {
    top_k: { min: 1, max: 100, type: "int" },
    keyword_weight: { min: 0, max: 1, type: "float" },
    vector_weight: { min: 0, max: 1, type: "float" },
  },
  ragflow_search: {
    top_k: { min: 1, max: 100, type: "int" },
    similarity_threshold: { min: 0, max: 1, type: "float" },
    vector_similarity_weight: { min: 0, max: 1, type: "float" },
  },
  idata_search: {
    top_k: { min: 1, max: 100, type: "int" },
    similarity_threshold: { min: -10, max: 1, type: "float" },
    keyword_similarity_weight: { min: 0, max: 1, type: "float" },
    vector_similarity_weight: { min: 0, max: 1, type: "float" },
  },
  tavily_search: { max_results: { min: 1, max: 100, type: "int" } },
  exa_search: { max_results: { min: 1, max: 100, type: "int" } },
  linkup_search: { max_results: { min: 1, max: 100, type: "int" } },
  terminal: { ssh_port: { min: 1, max: 65535, type: "int" } },
  get_email: { timeout: { min: 1, max: 600, type: "int" } },
};

// Get the numeric range (min/max/type) for a specific tool and parameter
export function getToolParamRange(
  toolName: string,
  paramName: string
): { min: number; max: number; type: "int" | "float" } | undefined {
  return TOOL_PARAM_RANGES[toolName]?.[paramName];
}

/**
 * Whether a tool param must hold a value when saving config / running a test.
 *
 * These are the optional-with-default params (top_k, threshold, search_mode,
 * max_results, ...) that the form lets the user clear. Clearing them leaves
 * the config silently empty (the SDK falls back to its default at runtime),
 * which is invisible to the user — so we treat them as required at save/test
 * time and prompt instead. Boolean enum options ([true, false]) are excluded:
 * they are rendered as switches and never empty.
 */
export function isToolParamRequiredOnSave(
  toolName: string,
  paramName: string
): boolean {
  if (getToolParamRange(toolName, paramName)) return true;
  const options = getToolParamOptions(toolName, paramName);
  if (options && options.some((o) => typeof o !== "boolean")) return true;
  return false;
}

/**
 * Constraint hint for a required-on-save param: its allowed range or enum
 * values, used to build the "required / allowed range / suggested default"
 * message shown next to the field and on save/test failure.
 */
export function getToolParamConstraintHint(
  toolName: string,
  paramName: string
): { kind: "range"; min: number; max: number } | { kind: "enum"; values: string[] } | { kind: "none" } {
  const range = getToolParamRange(toolName, paramName);
  if (range) return { kind: "range", min: range.min, max: range.max };
  const options = getToolParamOptions(toolName, paramName);
  if (options && options.some((o) => typeof o !== "boolean")) {
    return {
      kind: "enum",
      values: options
        .filter((o) => typeof o !== "boolean")
        .map((o) => String(o)),
    };
  }
  return { kind: "none" };
}

// Get options for a specific tool and parameter
export function getToolParamOptions(
  toolName: string,
  paramName: string
): string[] | boolean[] | undefined {
  const toolOptions =
    TOOL_PARAM_OPTIONS[toolName as keyof typeof TOOL_PARAM_OPTIONS];
  if (!toolOptions) return undefined;
  return toolOptions[paramName as keyof typeof toolOptions] as
    | string[]
    | boolean[]
    | undefined;
}
