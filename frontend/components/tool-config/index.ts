// Tool configuration related types and interfaces

import { KnowledgeBase } from "@/types/knowledgeBase";

// Re-export ToolKbType for use in other modules
export type ToolKbType =
  | "knowledge_base_search"
  | "dify_search"
  | "datamate_search"
  | "idata_search"
  | "haotian_search";

// Knowledge base selector component props
export interface KnowledgeBaseSelectorProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (selectedKnowledgeBases: KnowledgeBase[]) => void;
  selectedIds: string[];
  toolType: ToolKbType;
  title?: string;
  maxSelect?: number;
  showCreateButton?: boolean;
  showDeleteButton?: boolean;
  showCheckbox?: boolean;
  // Dify/iData configuration for fetching knowledge bases
  difyConfig?: {
    serverUrl?: string;
    apiKey?: string;
    userId?: string;
    knowledgeSpaceId?: string;
  };
}

// Get supported knowledge base sources for a tool type
export function getKnowledgeBaseSourcesForTool(toolType: ToolKbType): string[] {
  switch (toolType) {
    case "knowledge_base_search":
      return ["nexent"];
    case "dify_search":
      return ["dify"];
    case "datamate_search":
      return ["datamate"];
    case "idata_search":
      return ["idata"];
    default:
      return ["nexent"];
  }
}

// Mapping from skill name to tool type for knowledge base source filtering
const SKILL_TO_TOOL_MAP: Record<string, ToolKbType> = {
  "search-knowledge-base": "knowledge_base_search",
  "search-dify": "dify_search",
  "search-datamate": "datamate_search",
  "search-idata": "idata_search",
};

/**
 * Get the knowledge base source list for a given skill name.
 * This determines which knowledge bases (by source) are shown in the
 * knowledge base selector modal for each skill type.
 */
export function getKnowledgeBaseSourcesForSkill(skillName: string): string[] {
  const toolType = SKILL_TO_TOOL_MAP[skillName];
  return getKnowledgeBaseSourcesForTool(toolType);
}

/**
 * Get the tool type for a given skill name.
 * Returns the corresponding ToolKbType, or "knowledge_base_search" as default.
 */
export function getToolTypeForSkill(skillName: string): ToolKbType {
  return SKILL_TO_TOOL_MAP[skillName] || "knowledge_base_search";
}

/**
 * Check whether a skill has a knowledge-base-related parameter
 * that requires opening the knowledge base selector.
 * Supports both index_names (Nexent/DataMate) and dataset_ids (Dify/iData).
 */
export function skillRequiresKbSelection(params: { name: string }[]): boolean {
  return params.some(
    (p) => p.name === "index_names" || p.name === "dataset_ids"
  );
}

/**
 * Determine the parameter name used to store knowledge base IDs for a given skill.
 * Returns "index_names" for Nexent/DataMate, "dataset_ids" for Dify/iData.
 */
export function getKbParamNameForSkill(skillName: string): string {
  const toolType = getToolTypeForSkill(skillName);
  if (toolType === "dify_search" || toolType === "idata_search") {
    return "dataset_ids";
  }
  return "index_names";
}
