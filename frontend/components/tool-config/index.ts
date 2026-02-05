// Tool configuration related types and interfaces

import { KnowledgeBase } from "@/types/knowledgeBase";

// Knowledge base selector component props
export interface KnowledgeBaseSelectorProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (selectedKnowledgeBases: KnowledgeBase[]) => void;
  selectedIds: string[];
  toolType: "knowledge_base_search" | "dify_search" | "datamate_search";
  title?: string;
  maxSelect?: number;
  showCreateButton?: boolean;
  showDeleteButton?: boolean;
  showCheckbox?: boolean;
  // Dify configuration for fetching Dify knowledge bases
  difyConfig?: {
    serverUrl?: string;
    apiKey?: string;
  };
}

// Get supported knowledge base sources for a tool type
export function getKnowledgeBaseSourcesForTool(
  toolType: "knowledge_base_search" | "dify_search" | "datamate_search"
): string[] {
  switch (toolType) {
    case "knowledge_base_search":
      return ["nexent"];
    case "dify_search":
      return ["dify"];
    case "datamate_search":
      return ["datamate"];
    default:
      return ["nexent"];
  }
}
