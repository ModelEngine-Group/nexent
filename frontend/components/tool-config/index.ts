// Tool configuration related types and interfaces

import { KnowledgeBase } from "@/types/knowledgeBase";

// Knowledge base selector component props
export interface KnowledgeBaseSelectorProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (selectedKnowledgeBases: KnowledgeBase[]) => void;
  selectedIds: string[];
  toolType: "knowledge_base_search" | "dify_search" | "datamate_search" | "idata_search";
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
export function getKnowledgeBaseSourcesForTool(
  toolType: "knowledge_base_search" | "dify_search" | "datamate_search" | "idata_search"
): string[] {
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
