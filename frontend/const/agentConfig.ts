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
