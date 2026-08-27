import type { Tool, ToolParam } from "@/types/agentConfig";

// Shared tool helpers used by Agent configuration and NL2Agent resource cards.

export function findCanonicalTool(
  tools: Tool[],
  toolId: string | number
): Tool | undefined {
  return tools.find((tool) => String(tool.id) === String(toolId));
}

export function mergeCanonicalTool(tool: Tool, tools: Tool[]): Tool {
  const canonical = findCanonicalTool(tools, tool.id);
  if (!canonical) return tool;

  return {
    ...tool,
    ...canonical,
    initParams: tool.initParams,
  };
}

export function mergeToolParamValues(
  params: ToolParam[],
  values: Record<string, unknown> | null | undefined
): ToolParam[] {
  if (!values) return params.map((param) => ({ ...param }));

  return params.map((param) =>
    Object.prototype.hasOwnProperty.call(values, param.name)
      ? { ...param, value: values[param.name] }
      : { ...param }
  );
}

export const TOOLS_REQUIRING_KB_SELECTION = [
  "dify_search",
  "datamate_search",
  "idata_search",
  "haotian_search",
  "ragflow_search",
];
export const TOOLS_REQUIRING_EMBEDDING = ["knowledge_base_search"];
export const TOOLS_REQUIRING_IMAGE_UNDERSTANDING = ["analyze_image"];
export const TOOLS_REQUIRING_AUDIO_UNDERSTANDING = ["analyze_audio"];
export const TOOLS_REQUIRING_VIDEO_UNDERSTANDING = ["analyze_video"];

export function getToolKbType(name: string) {
  if (!TOOLS_REQUIRING_KB_SELECTION.includes(name)) return null;
  if (name === "dify_search") return "dify_search" as const;
  if (name === "datamate_search") return "datamate_search" as const;
  if (name === "idata_search") return "idata_search" as const;
  if (name === "haotian_search") return "haotian_search" as const;
  if (name === "aidp_search") return "aidp_search" as const;
  if (name === "ragflow_search") return "ragflow_search" as const;
  return "knowledge_base_search" as const;
}

export function getToolLabels(tool: Tool): string[] {
  return Array.isArray(tool.labels) ? tool.labels : [];
}
