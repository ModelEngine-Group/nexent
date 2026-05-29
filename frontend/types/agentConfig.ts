// Agent Configuration Types
import type { Dispatch, SetStateAction } from "react";

import { ChatMessageType } from "./chat";
import { ModelOption } from "@/types/modelConfig";
import { GENERATE_PROMPT_STREAM_TYPES } from "../const/agentConfig";
import type { PromptTemplateFieldKey } from "../const/promptTemplate";

export type AgentConfigUpdate = Partial<Pick<
  Agent,
  | "name"
  | "display_name"
  | "author"
  | "model"
  | "model_id"
  | "max_step"
  | "provide_run_summary"
  | "description"
  | "duty_prompt"
  | "constraint_prompt"
  | "few_shots_prompt"
  | "business_description"
  | "business_logic_model_id"
  | "business_logic_model_name"
  | "prompt_template_id"
  | "prompt_template_name"
  | "group_ids"
  | "ingroup_permission"
>>;

// ========== Core Interfaces ==========

export interface Agent {
  id: string;
  name: string;
  display_name?: string;
  description: string;
  author?: string;
  unavailable_reasons?: string[];
  model: string;
  model_id?: number;
  max_step: number;
  provide_run_summary: boolean;
  enable_context_manager?: boolean;
  tools: Tool[];
  skills?: Skill[];  // Skills configured for this agent
  duty_prompt?: string;
  constraint_prompt?: string;
  few_shots_prompt?: string;
  business_description?: string;
  business_logic_model_name?: string;
  business_logic_model_id?: number;
  prompt_template_id?: number;
  prompt_template_name?: string;
  is_available?: boolean;
  is_new?: boolean;
  sub_agent_id_list?: number[];
  external_sub_agent_id_list?: number[];  // External A2A agent IDs
  group_ids?: number[];
  ingroup_permission?: "EDIT" | "READ_ONLY" | "PRIVATE";
  /**
   * Per-agent permission returned by /agent/list.
   * EDIT: editable, READ_ONLY: read-only.
   */
  permission?: "EDIT" | "READ_ONLY";
  /** When true, system prompts were withheld (ASSET_OWNER agent viewed by non-ASSET_OWNER caller). */
  prompts_hidden?: boolean;
  current_version_no?: number;
  is_a2a_server?: boolean;
}

export interface Tool {
  id: string;
  name: string;
  origin_name?: string;
  description: string;
  description_zh?: string;
  source?: string;
  initParams: ToolParam[];
  is_available?: boolean;
  create_time?: string;
  usage?: string;
  inputs?: string;
  category?: string;
  /**
   * Knowledge base display names associated with this tool.
   * This is populated when the tool (e.g., knowledge_base_search) has knowledge bases configured.
   * Used to pass knowledge base names to prompt generation without requiring database lookup.
   */
  display_names?: string[];
}

export interface ToolParam {
  name: string;
  type: "string" | "number" | "boolean" | "array" | "object" | "Optional";
  required: boolean;
  value?: any;
  description?: string;
  description_zh?: string;
  default?: string;
  depends_on?: string;
}

export interface SkillParam {
  name: string;
  type: "string" | "number" | "boolean" | "array" | "object" | "Optional";
  required: boolean;
  value?: any;
  description_en?: string;
  description_zh?: string;
  depends_on?: string;
}



// ========== Data Interfaces ==========

export interface AgentConfigDataResponse {
  businessLogic: string;
  systemPrompt: string;
}

// Tool group interface
export interface ToolGroup {
  key: string;
  label: string;
  tools: Tool[];
  subGroups?: ToolSubGroup[];
}

// Tool sub-group interface for secondary grouping
export interface ToolSubGroup {
  key: string;
  label: string;
  tools: Tool[];
}

// Skill interface for skill management
export interface Skill {
  skill_id: number;
  tenant_id?: string;
  name: string;
  description: string;
  source: string;
  tags?: string[];
  content?: string;
  config_schemas?: SkillParam[] | null;
  config_values?: Record<string, any> | null;
  tool_ids?: number[];
  update_time?: string;
  create_time?: string;
}

// Skill group interface for tab organization
export interface SkillGroup {
  key: string;
  label: string;
  skills: Skill[];
}

// Skill with installation status for tenant creation flow
export type SkillInstallStatus = "installable" | "installed" | "resource_missing";

export interface InstallableSkill {
  skill_id: number;
  name: string;
  description: string;
  source: string;
  status: SkillInstallStatus;
}

// Tree structure node type
export interface TreeNodeDatum {
  name: string;
  type?: string;
  color?: string;
  count?: string;
  children?: TreeNodeDatum[];
  depth?: number;
  attributes?: { toolType?: string };
}

// ========== Component Props Interfaces ==========

// Main component props interface for AgentSetupOrchestrator
export interface AgentSetupOrchestratorProps {
  businessLogic: string;
  setBusinessLogic: (value: string) => void;
  businessLogicError?: boolean;
  selectedTools: Tool[];
  setSelectedTools: Dispatch<SetStateAction<Tool[]>>;
  isCreatingNewAgent: boolean;
  setIsCreatingNewAgent: (value: boolean) => void;
  mainAgentModel: string | null;
  setMainAgentModel: (value: string | null) => void;
  mainAgentModelId: number | null;
  setMainAgentModelId: (value: number | null) => void;
  mainAgentMaxStep: number;
  setMainAgentMaxStep: (value: number) => void;
  businessLogicModel: string | null;
  setBusinessLogicModel: (value: string | null) => void;
  businessLogicModelId: number | null;
  setBusinessLogicModelId: (value: number | null) => void;
  tools: Tool[];
  subAgentList?: Agent[];
  loadingAgents?: boolean;
  mainAgentId: string | null;
  setMainAgentId: (value: string | null) => void;
  setSubAgentList: (agents: Agent[]) => void;
  enabledAgentIds: number[];
  setEnabledAgentIds: (ids: number[]) => void;
  onEditingStateChange?: (isEditing: boolean, agent: any) => void;
  onToolsRefresh: (showSuccessMessage?: boolean) => void | Promise<any>;
  dutyContent: string;
  setDutyContent: (value: string) => void;
  constraintContent: string;
  setConstraintContent: (value: string) => void;
  fewShotsContent: string;
  setFewShotsContent: (value: string) => void;
  agentName?: string;
  setAgentName?: (value: string) => void;
  agentDescription?: string;
  setAgentDescription?: (value: string) => void;
  agentDisplayName?: string;
  setAgentDisplayName?: (value: string) => void;
  agentAuthor?: string;
  setAgentAuthor?: (value: string) => void;
  isGeneratingAgent?: boolean;
  onDebug?: () => void;
  getCurrentAgentId?: () => number | undefined;
  onGenerateAgent?: (selectedModel?: ModelOption) => void;
  onExportAgent?: () => void;
  onDeleteAgent?: () => void;
  editingAgent?: any;
  onExitCreation?: () => void;
  isEmbeddingConfigured?: boolean;
  /** notify parent about unsaved state changes */
  onUnsavedChange?: (dirty: boolean) => void;
  /** register a save-all handler for parent to invoke */
  registerSaveHandler?: (handler: () => Promise<void>) => void;
  /** register a reload handler for parent to invoke */
  registerReloadHandler?: (handler: () => Promise<void>) => void;
}

// SubAgentPool component props interface
export interface SubAgentPoolProps {
  onEditAgent: (agent: Agent) => void;
  onCreateNewAgent: () => void;
  onImportAgent: () => void;
  onExitEditMode?: () => void;
  subAgentList?: Agent[];
  loadingAgents?: boolean;
  isImporting?: boolean;
  isGeneratingAgent?: boolean;
  editingAgent?: Agent | null;
  isCreatingNewAgent?: boolean;
  onCopyAgent?: (agent: Agent) => void;
  onExportAgent?: (agent: Agent) => void;
  onDeleteAgent?: (agent: Agent) => void;
}

// ToolPool component props interface
export interface ToolPoolProps {
  selectedTools: Tool[];
  onSelectTool: (tool: Tool, isSelected: boolean) => void;
  onToolConfigSave?: (tool: Tool) => void;
  tools?: Tool[];
  loadingTools?: boolean;
  mainAgentId?: string | null;
  localIsGenerating?: boolean;
  onToolsRefresh?: (showSuccessMessage?: boolean) => void | Promise<any>;
  isEditingMode?: boolean;
  isGeneratingAgent?: boolean;
  isEmbeddingConfigured?: boolean;
  agentUnavailableReasons?: string[];
  toolConfigDrafts?: Record<string, ToolParam[]>;
}

// Simple prompt editor props interface
export interface SimplePromptEditorProps {
  value: string;
  onChange: (value: string) => void;
  height?: string | number;
  bordered?: boolean;
}

// CollaborativeAgentDisplay component props interface
export interface CollaborativeAgentDisplayProps {
  availableAgents: Agent[];
  selectedAgentIds: number[];
  parentAgentId?: number;
  onAgentIdsChange: (newAgentIds: number[]) => void;
  isEditingMode: boolean;
  isGeneratingAgent: boolean;
  className?: string;
  style?: React.CSSProperties;
}

// ToolConfigModal component props interface


// ExpandEditModal component props interface
export interface ExpandEditModalProps {
  open: boolean;
  title: string;
  content: string;
  index: number;
  onClose: () => void;
  onSave: (content: string) => void;
}

// AgentDebugging component props interface
export interface AgentDebuggingProps {
  onAskQuestion: (question: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  messages: ChatMessageType[];
}

// DebugConfig component props interface
export interface DebugConfigProps {
  agentId?: number; // Make agentId an optional prop
}

// McpConfigModal component props interface
export interface McpConfigModalProps {
  visible: boolean;
  onCancel: () => void;
}

// ========== Agent Call Relationship Interfaces ==========

// Agent call relationship related types
export interface AgentCallRelationshipTool {
  tool_id: string;
  name: string;
  type: string;
}

export interface AgentCallRelationshipSubAgent {
  agent_id: string;
  name: string;
  tools: AgentCallRelationshipTool[];
  sub_agents: AgentCallRelationshipSubAgent[];
  depth?: number;
}

export interface AgentCallRelationship {
  agent_id: string;
  name: string;
  tools: AgentCallRelationshipTool[];
  sub_agents: AgentCallRelationshipSubAgent[];
}

export interface AgentCallRelationshipModalProps {
  visible: boolean;
  onClose: () => void;
  agentId: number;
  agentName: string;
}

// Agent call relationship tree node data
export interface AgentCallRelationshipTreeNodeDatum {
  name: string;
  type?: string;
  color?: string;
  count?: string;
  children?: AgentCallRelationshipTreeNodeDatum[];
  depth?: number;
  attributes?: { toolType?: string };
}

// ========== Layout and Configuration Interfaces ==========

// Layout configuration interface
export interface LayoutConfig {
  CARD_HEADER_PADDING: string;
  CARD_BODY_PADDING: string;
  DRAWER_WIDTH: string;
}

// ========== Event Interfaces ==========

// Custom event types for agent configuration
export interface AgentConfigCustomEvent extends CustomEvent {
  detail: AgentConfigDataResponse;
}

// Agent refresh event
export interface AgentRefreshEvent extends CustomEvent {
  detail: any;
}

// ========== MCP Interfaces ==========

// MCP server interface definition
export interface McpServer {
  service_name: string;
  mcp_url: string;
  status: boolean;
  remote_mcp_server_name?: string;
  remote_mcp_server?: string;
  authorization_token?: string | null;
  custom_headers?: Record<string, string> | null;
  mcp_id: number;
  /**
   * Per-item permission returned by /mcp/list.
   * EDIT: editable, READ_ONLY: read-only.
   */
  permission?: "EDIT" | "READ_ONLY";
}

// MCP tool interface definition
export interface McpTool {
  name: string;
  description: string;
  parameters?: any;
}

// MCP container interface definition
export interface McpContainer {
  container_id: string;
  name?: string;
  status?: string;
  mcp_url?: string;
  host_port?: number;
  /**
   * Per-item permission returned by /mcp/containers.
   * EDIT: editable, READ_ONLY: read-only.
   */
  permission?: "EDIT" | "READ_ONLY";
}

// ========== Prompt Service Interfaces ==========

/**
 * Prompt Generation Request Parameters
 */
export interface GeneratePromptParams {
  agent_id: number;
  task_description: string;
  model_id: number;
  prompt_template_id?: number;
  tool_ids?: number[]; // Optional: tool IDs selected in frontend (takes precedence over database query)
  sub_agent_ids?: number[]; // Optional: sub-agent IDs selected in frontend (takes precedence over database query)
  /**
   * Optional: Knowledge base display names for few-shot examples.
   * If provided, the backend will use these instead of querying the database.
   * This allows the frontend to pass the latest configured knowledge base names
   * without waiting for tool config to be saved first.
   */
  knowledge_base_display_names?: string[];
  /**
   * Whether tools or sub-agents are selected.
   * When false, the backend skips generating constraint and few_shots sections.
   */
  has_selected_resources?: boolean;
}

export interface OptimizePromptSectionParams {
  agent_id: number;
  task_description: string;
  model_id: string;
  section_type: "duty" | "constraint" | "few_shots";
  section_title: string;
  current_content: string;
  feedback: string;
  tool_ids?: number[];
  sub_agent_ids?: number[];
  knowledge_base_display_names?: string[];
}

export interface OptimizePromptSectionResponse {
  section_type: "duty" | "constraint" | "few_shots";
  section_title: string;
  original_content: string;
  optimized_content: string;
}

/**
 * Stream Response Data Structure
 */
export interface StreamResponseData {
  type: (typeof GENERATE_PROMPT_STREAM_TYPES)[keyof typeof GENERATE_PROMPT_STREAM_TYPES];
  content: string;
  is_complete: boolean;
}

export type PromptTemplateContent = Record<PromptTemplateFieldKey, string>;

export interface PromptTemplate {
  template_id: number;
  template_name: string;
  description?: string | null;
  template_type: string;
  template_content_zh: PromptTemplateContent;
  template_content_en?: PromptTemplateContent | null;
  is_system_default?: boolean;
  create_time?: string;
  update_time?: string;
}

export interface PromptTemplatePayload {
  template_name: string;
  description?: string;
  template_type?: string;
  template_content_zh: PromptTemplateContent;
  template_content_en?: PromptTemplateContent | null;
}
