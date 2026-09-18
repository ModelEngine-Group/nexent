import type { ConversationKnowledgeScope } from "@/types/knowledgeScope";

export type WorkbenchMode =
  | "generic_chat"
  | "single_agent_chat"
  | "multi_agent_chat"
  | "skill_create"
  | "agent_create";

export interface WorkbenchSkillMount {
  skill_id: number;
  config_values: Record<string, unknown>;
}

export interface WorkbenchAgentMount {
  agent_id: number;
  version_no?: number;
}

export interface WorkbenchSessionConfig {
  schema_version: 3;
  mode: WorkbenchMode;
  model_id?: number;
  generation_config: {
    deep_thinking: boolean;
    temperature?: number;
    top_p?: number;
    requested_output_tokens?: number;
  };
  agent_mounts: WorkbenchAgentMount[];
  skill_mounts: WorkbenchSkillMount[];
  knowledge_scope?: ConversationKnowledgeScope;
}

export interface WorkbenchCapabilityPreview {
  agent_id: number;
  version_no: number;
  default_skill_mounts: WorkbenchSkillMount[];
  default_skill_resources?: Array<{
    skill_id: number;
    name: string;
    description: string;
  }>;
  knowledge: Record<string, unknown>;
}

export interface WorkbenchBootstrap {
  schema_version: 3;
  modes: Record<WorkbenchMode, { enabled: boolean }>;
}

export interface WorkbenchResourceControls {
  agentName?: string;
  agents?: Array<{ id: number; name: string; remove: () => void }>;
  skills: Array<{ id: number; name: string }>;
  onSelectAgent: () => void;
  onRemoveAgent: () => void;
  creationActions?: import("react").ReactNode;
}

export interface WorkbenchComposerPresentation {
  mode: WorkbenchMode;
  onExitCreation: () => void;
  actions: import("react").ReactNode;
}
