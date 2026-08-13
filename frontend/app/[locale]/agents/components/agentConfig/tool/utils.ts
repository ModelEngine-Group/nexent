// Shared tool helpers used by both ToolManagement and SelectToolsDialog.

export const TOOLS_REQUIRING_KB_SELECTION = [
  "knowledge_base_search", "dify_search", "datamate_search",
  "idata_search", "haotian_search", "ragflow_search", "aidp_search",
];
export const TOOLS_REQUIRING_EMBEDDING = ["knowledge_base_search"];
export const TOOLS_REQUIRING_IMAGE_UNDERSTANDING = ["analyze_image"];
export const TOOLS_REQUIRING_VIDEO_UNDERSTANDING = ["analyze_audio", "analyze_video"];

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

export function getToolLabels(tool: any): string[] {
  return Array.isArray(tool.labels) ? tool.labels : [];
}
