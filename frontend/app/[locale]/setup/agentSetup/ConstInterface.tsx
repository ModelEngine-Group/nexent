"use client";

// model enum class
export enum OpenAIModel {
  MainModel = 'main_model',
  SubModel = 'sub_model'
}

export interface Agent {
  id: string;
  name: string;
  description: string;
  model: string;
  max_step: number;
  provide_run_summary: boolean;
  tools: Tool[];
  prompt: string;
  business_description?: string;
  is_available?: boolean;
}

export interface Tool {
  id: string;
  name: string;
  description: string;
  source: 'local' | 'mcp';
  initParams: ToolParam[];
  is_available?: boolean;
}

export interface ToolParam {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'array' | 'object' | 'OpenAIModel' | 'Optional';
  required: boolean;
  value?: any;
  description?: string;
}

// business logic input component props interface
export interface BusinessLogicInputProps {
  value: string;
  onChange: (value: string) => void;
  selectedAgents: Agent[];
  systemPrompt: string;
}
// sub agent pool component props interface
export interface SubAgentPoolProps {
  selectedAgents: Agent[];
  onSelectAgent: (agent: Agent, isSelected: boolean) => void;
  onEditAgent: (agent: Agent) => void;
  onCreateNewAgent: () => void;
  onImportAgent: () => void;
  onExportAgent: (agent: Agent) => void;
  onDeleteAgent: (agent: Agent) => void;
  subAgentList?: Agent[];
  loadingAgents?: boolean;
  enabledAgentIds?: number[];
  isImporting?: boolean;
}
// tool pool component props interface
export interface ToolPoolProps {
  selectedTools: Tool[];
  onSelectTool: (tool: Tool, isSelected: boolean) => void;
  isCreatingNewAgent?: boolean;
  tools?: Tool[];
  loadingTools?: boolean;
  mainAgentId?: string | null;
  localIsGenerating?: boolean;
  onToolsRefresh?: () => void;
}
// main component props interface
export interface BusinessLogicConfigProps {
  businessLogic: string;
  setBusinessLogic: (value: string) => void;
  selectedAgents: Agent[];
  setSelectedAgents: (agents: Agent[]) => void;
  selectedTools: Tool[];
  setSelectedTools: (tools: Tool[] | ((prevTools: Tool[]) => Tool[])) => void;
  systemPrompt: string;
  setSystemPrompt: (value: string) => void;
  isCreatingNewAgent: boolean;
  setIsCreatingNewAgent: (value: boolean) => void;
  mainAgentModel: OpenAIModel;
  setMainAgentModel: (value: OpenAIModel) => void;
  mainAgentMaxStep: number;
  setMainAgentMaxStep: (value: number) => void;
  tools?: Tool[];
  subAgentList?: Agent[];
  loadingAgents?: boolean;
  mainAgentId: string | null;
  setMainAgentId: (id: string | null) => void;
  setSubAgentList: (agents: Agent[]) => void;
  enabledAgentIds: number[];
  setEnabledAgentIds: (ids: number[]) => void;
  newAgentName: string;
  newAgentDescription: string;
  newAgentProvideSummary: boolean;
  setNewAgentName: (name: string) => void;
  setNewAgentDescription: (description: string) => void;
  setNewAgentProvideSummary: (provide: boolean) => void;
  isNewAgentInfoValid: boolean;
  setIsNewAgentInfoValid: (valid: boolean) => void;
  onEditingStateChange?: (isEditing: boolean, editingAgent: Agent | null) => void;
  onToolsRefresh?: () => void;
}
