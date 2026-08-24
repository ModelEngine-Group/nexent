import type { Tool } from "@/types/agentConfig";

export const MANAGED_KNOWLEDGE_TOOL_NAMES = [
  "knowledge_base_search",
  "aidp_search",
] as const;

export type ManagedKnowledgeToolName =
  (typeof MANAGED_KNOWLEDGE_TOOL_NAMES)[number];

export const getSemanticToolName = (tool: Pick<Tool, "name" | "origin_name">) =>
  tool.origin_name || tool.name;

export const isManagedKnowledgeTool = (
  tool: Pick<Tool, "name" | "origin_name">
): boolean =>
  MANAGED_KNOWLEDGE_TOOL_NAMES.includes(
    getSemanticToolName(tool) as ManagedKnowledgeToolName
  );
