// Agent Configuration Types
import { ChatMessageType } from "./chat";
import { ModelOption } from "@/types/modelConfig";
import { GENERATE_PROMPT_STREAM_TYPES } from "../const/agentConfig";

// ========== Core Interfaces ==========

export interface Agent {
  id: string;
  name: string;
  display_name?: string;
  description: string;
  model: string;
  model_id?: number;
  max_step: number;
  provide_run_summary: boolean;
  tools: Tool[];
  duty_prompt?: string;
  constraint_prompt?: string;
  few_shots_prompt?: string;
  business_description?: string;
  is_available?: boolean;
  sub_agent_id_list?: number[];
}

export interface Tool {
  id: string;
  name: string;
  origin_name?: string;
  description: string;
  source: "local" | "mcp" | "langchain";
  initParams: ToolParam[];
  is_available?: boolean;
  create_time?: string;
  usage?: string;
  inputs?: string;
  category?: string;
}

export interface ToolParam {
  name: string;
  type: "string" | "number" | "boolean" | "array" | "object" | "Optional";
  required: boolean;
  value?: any;
  description?: string;
}

// ========== Data Interfaces ==========

// Agent configuration data response interface
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
  selectedTools: Tool[];
  setSelectedTools: (tools: Tool[]) => void;
  isCreatingNewAgent: boolean;
  setIsCreatingNewAgent: (value: boolean) => void;
  mainAgentModel: string | null;
  setMainAgentModel: (value: string | null) => void;
  mainAgentModelId: number | null;
  setMainAgentModelId: (value: number | null) => void;
  mainAgentMaxStep: number;
  setMainAgentMaxStep: (value: number) => void;
  tools: Tool[];
  subAgentList?: Agent[];
  loadingAgents?: boolean;
  mainAgentId: string | null;
  setMainAgentId: (value: string | null) => void;
  setSubAgentList: (agents: Agent[]) => void;
  enabledAgentIds: number[];
  setEnabledAgentIds: (ids: number[]) => void;
  onEditingStateChange?: (isEditing: boolean, agent: any) => void;
  onToolsRefresh: () => void;
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
  isGeneratingAgent?: boolean;
  onDebug?: () => void;
  getCurrentAgentId?: () => number | undefined;
  onGenerateAgent?: (selectedModel?: ModelOption) => void;
  onExportAgent?: () => void;
  onDeleteAgent?: () => void;
  editingAgent?: any;
  onExitCreation?: () => void;
  isEmbeddingConfigured?: boolean;
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
}

// ToolPool component props interface
export interface ToolPoolProps {
  selectedTools: Tool[];
  onSelectTool: (tool: Tool, isSelected: boolean) => void;
  tools?: Tool[];
  loadingTools?: boolean;
  mainAgentId?: string | null;
  localIsGenerating?: boolean;
  onToolsRefresh?: () => void;
  isEditingMode?: boolean;
  isGeneratingAgent?: boolean;
  isEmbeddingConfigured?: boolean;
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
export interface ToolConfigModalProps {
  isOpen: boolean;
  onCancel: () => void;
  onSave: (tool: Tool) => void;
  tool: Tool | null;
  mainAgentId: number;
  selectedTools?: Tool[];
  isEditingMode?: boolean;
}

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
}

// MCP tool interface definition
export interface McpTool {
  name: string;
  description: string;
  parameters?: any;
}

// ========== Prompt Service Interfaces ==========

/**
 * Prompt Generation Request Parameters
 */
export interface GeneratePromptParams {
  agent_id: number;
  task_description: string;
  model_id: string;
}

/**
 * Stream Response Data Structure
 */
export interface StreamResponseData {
  type: (typeof GENERATE_PROMPT_STREAM_TYPES)[keyof typeof GENERATE_PROMPT_STREAM_TYPES];
  content: string;
  is_complete: boolean;
}
