/**
 * agentConfigStore
 *
 * Purpose:
 * - Manage Agent configuration editing state across AgentManage, AgentConfig, AgentInfo
 * - Track baseline vs. edited data
 * - Expose hasUnsavedChanges whenever any tracked field changes
 *
 */

import { create } from "zustand";

import { Agent, Tool, AgentConfigUpdate, Skill } from "@/types/agentConfig";
import { getAgentGenerationCache } from "@/lib/agentGenerationCache";

/**
 * Fields we need to track for dirty detection and editing.
 * Based on Agent interface with snake_case field names.
 * Includes all editable fields from Agent interface (excluding id).
 * tools field represents the selected/enabled tools.
 */
export type EditableAgent = Pick<
  Agent,
  | "name"
  | "display_name"
  | "description"
  | "author"
  | "model"
  | "model_id"
  | "max_step"
  | "provide_run_summary"
  | "tools"
  | "duty_prompt"
  | "constraint_prompt"
  | "few_shots_prompt"
  | "business_description"
  | "business_logic_model_name"
  | "business_logic_model_id"
  | "prompt_template_id"
  | "prompt_template_name"
  | "sub_agent_id_list"
  | "group_ids"
  | "ingroup_permission"
> & {
  skills: Skill[];
  external_sub_agent_id_list?: number[];
  prompts_hidden?: boolean;
};

interface AgentConfigStoreState {
  currentAgentId: number | null;
  currentAgentPermission: "EDIT" | "READ_ONLY" | null;
  baselineAgent: EditableAgent | null;
  editedAgent: EditableAgent;
  hasUnsavedChanges: boolean;
  isCreatingMode: boolean; // true when user is in create mode, even if currentAgentId is null
  isGenerating: boolean; // true when agent generation is in progress
  defaultLlmConfig: { id: number | null; name: string; displayName: string } | null;

  forceRefreshKey: number;

  /**
   * Check if the current agent should be read-only.
   * - isCreatingMode: always editable (new agent)
   * - currentAgentPermission === 'READ_ONLY': always read-only
   * - currentAgentPermission === null: unknown, assume editable
   */
  isReadOnly: () => boolean;

  /**
   * Set current agent (null = create mode).
   * Resets baseline and edited state.
   */
  setCurrentAgent: (agent: Agent | null) => void;

  /**
   * Enter create mode. Sets isCreatingMode to true and resets state.
   */
  enterCreateMode: () => void;

  /**
   * Trigger a UI force-refresh by incrementing forceRefreshKey.
   * Call this after operations like rollback that need to force-reload form state.
   */
  triggerForceRefresh: () => void;


  /**
   * Update tools (selected tools).
   */
  updateTools: (tools: Tool[]) => void;

  /**
   * Update skills (selected skills).
   */
  updateSkills: (skills: Skill[]) => void;

  /**
   * Update sub_agent_id_list (Component B).
   */
  updateSubAgentIds: (ids: number[]) => void;

  /**
   * Update external_sub_agent_id_list.
   */
  updateExternalSubAgentIds: (ids: number[]) => void;

  /**
   * Update agent configuration fields.
   * Used for both generation and manual editing.
   */
  updateAgentConfig: (payload: AgentConfigUpdate) => void;

  /**
   * Mark changes as saved: move edited -> baseline, clear hasUnsavedChanges.
   */
  markAsSaved: () => void;

  /**
   * Discard changes: revert edited to baseline.
   */
  discardChanges: () => void;

  /**
   * Set generating state (used during agent generation).
   */
  setIsGenerating: (value: boolean) => void;

  /**
   * Reset all state (optional).
   */
  reset: () => void;

  /**
   * Set the default LLM config from load_config interface.
   * Updates the emptyEditableAgent defaults for model fields.
   */
  setDefaultLlmConfig: (config: { id: number | null; name: string; displayName: string } | null) => void;

  /**
   * Get the current baseline editable agent (null = create or initial state).
   * Use isCreatingMode to distinguish between initial state and create mode.
   */
  getCurrentAgent: () => EditableAgent | null;
}

/**
 * Factory function to create an empty editable agent.
 * Initializes model fields from the default LLM config when available.
 */
function createEmptyEditableAgent(llmConfig?: { id: number | null; name: string; displayName: string }): EditableAgent {
  return {
    name: "",
    display_name: "",
    description: "",
    author: "",
    model: llmConfig?.name || "",
    model_id: llmConfig?.id || 0,
    max_step: 15,
    provide_run_summary: false,
    tools: [],
    skills: [],
    duty_prompt: "",
    constraint_prompt: "",
    few_shots_prompt: "",
    business_description: "",
    business_logic_model_name: llmConfig?.name || "",
    business_logic_model_id: llmConfig?.id || 0,
    prompt_template_id: 0,
    prompt_template_name: "system_default",
    sub_agent_id_list: [],
    group_ids: [],
    ingroup_permission: "READ_ONLY",
  };
}

const emptyEditableAgent: EditableAgent = createEmptyEditableAgent();

const toEditable = (agent: Agent | null): EditableAgent =>
  agent
    ? {
        name: agent.name,
        display_name: agent.display_name || "",
        description: agent.description,
        author: agent.author || "",
        model: agent.model,
        model_id: agent.model_id || 0,
        max_step: agent.max_step,
        provide_run_summary: agent.provide_run_summary,
        tools: [...(agent.tools || [])],
        skills: [...(agent.skills || [])],
        duty_prompt: agent.duty_prompt || "",
        constraint_prompt: agent.constraint_prompt || "",
        few_shots_prompt: agent.few_shots_prompt || "",
        business_description: agent.business_description || "",
        business_logic_model_name: agent.business_logic_model_name || "",
        business_logic_model_id: agent.business_logic_model_id || 0,
        prompt_template_id: agent.prompt_template_id ?? 0,
        prompt_template_name: agent.prompt_template_name || "system_default",
        sub_agent_id_list: agent.sub_agent_id_list || [],
        external_sub_agent_id_list: agent.external_sub_agent_id_list || [],
        group_ids: agent.group_ids || [],
        ingroup_permission: agent.ingroup_permission || "READ_ONLY",
        prompts_hidden: agent.prompts_hidden,
      }
    : { ...emptyEditableAgent };

/**
 * Generic dirty check: compare baseline vs edited, ignoring null baseline.
 * For complex fields (tools, skills), use custom comparators.
 */
const normalizeArray = (arr: number[]) =>
  Array.from(new Set((arr ?? []).map((n) => Number(n)).filter((n) => !isNaN(n)))).sort(
    (a, b) => a - b
  );

const isToolsDirty = (baselineTools: Tool[], editedTools: Tool[]): boolean => {
  if (baselineTools.length !== editedTools.length) {
    return true;
  }

  const sortedBaseline = [...baselineTools].sort((a, b) => Number(a.id) - Number(b.id));
  const sortedEdited = [...editedTools].sort((a, b) => Number(a.id) - Number(b.id));

  for (let i = 0; i < sortedBaseline.length; i++) {
    const baseTool = sortedBaseline[i];
    const editTool = sortedEdited[i];

    if (Number(baseTool.id) !== Number(editTool.id)) {
      return true;
    }

    const baseParams = baseTool.initParams || [];
    const editParams = editTool.initParams || [];

    if (baseParams.length !== editParams.length) {
      return true;
    }

    for (const baseParam of baseParams) {
      const editParam = editParams.find(p => p.name === baseParam.name);
      if (!editParam) {
        return true;
      }

      const baseValue = baseParam.value;
      const editValue = editParam.value;

      if (Array.isArray(baseValue) && Array.isArray(editValue)) {
        if (baseValue.length !== editValue.length) {
          return true;
        }
        const sortedBase = [...baseValue].sort();
        const sortedEdit = [...editValue].sort();
        if (JSON.stringify(sortedBase) !== JSON.stringify(sortedEdit)) {
          return true;
        }
      } else if (
        baseValue !== null &&
        editValue !== null &&
        typeof baseValue === 'object' &&
        typeof editValue === 'object'
      ) {
        if (JSON.stringify(baseValue) !== JSON.stringify(editValue)) {
          return true;
        }
      } else if (baseValue !== editValue) {
        return true;
      }
    }
  }

  return false;
};

const isSkillsDirty = (baselineSkills: Skill[], editedSkills: Skill[]): boolean => {
  if (baselineSkills.length !== editedSkills.length) {
    return true;
  }

  const sortedBaseline = [...baselineSkills].sort((a, b) => Number(a.skill_id) - Number(b.skill_id));
  const sortedEdited = [...editedSkills].sort((a, b) => Number(a.skill_id) - Number(b.skill_id));

  for (let i = 0; i < sortedBaseline.length; i++) {
    if (sortedBaseline[i].skill_id !== sortedEdited[i].skill_id) {
      return true;
    }
  }

  return false;
};

const isDirty = (
  baselineAgent: EditableAgent | null,
  editedAgent: EditableAgent
): boolean => {
  if (!baselineAgent) {
    return (
      editedAgent.name !== "" ||
      editedAgent.display_name !== "" ||
      editedAgent.description !== "" ||
      editedAgent.author !== "" ||
      editedAgent.model !== "" ||
      editedAgent.model_id !== 0 ||
      editedAgent.max_step !== 0 ||
      editedAgent.provide_run_summary !== false ||
      editedAgent.duty_prompt !== "" ||
      editedAgent.constraint_prompt !== "" ||
      editedAgent.few_shots_prompt !== "" ||
      editedAgent.business_description !== "" ||
      editedAgent.business_logic_model_name !== "" ||
      editedAgent.business_logic_model_id !== 0 ||
      (editedAgent.prompt_template_id ?? 0) !== 0 ||
      (editedAgent.prompt_template_name || "system_default") !== "system_default" ||
      normalizeArray(editedAgent.group_ids || []).length > 0 ||
      normalizeArray(editedAgent.sub_agent_id_list || []).length > 0 ||
      normalizeArray(editedAgent.external_sub_agent_id_list || []).length > 0 ||
      editedAgent.tools.length > 0 ||
      editedAgent.skills.length > 0 ||
      editedAgent.ingroup_permission !== "READ_ONLY"
    );
  }

  return (
    baselineAgent.name !== editedAgent.name ||
    baselineAgent.display_name !== editedAgent.display_name ||
    baselineAgent.description !== editedAgent.description ||
    baselineAgent.author !== editedAgent.author ||
    baselineAgent.model !== editedAgent.model ||
    baselineAgent.model_id !== editedAgent.model_id ||
    baselineAgent.max_step !== editedAgent.max_step ||
    baselineAgent.provide_run_summary !== editedAgent.provide_run_summary ||
    baselineAgent.duty_prompt !== editedAgent.duty_prompt ||
    baselineAgent.constraint_prompt !== editedAgent.constraint_prompt ||
    baselineAgent.few_shots_prompt !== editedAgent.few_shots_prompt ||
    baselineAgent.business_description !== editedAgent.business_description ||
    baselineAgent.business_logic_model_name !== editedAgent.business_logic_model_name ||
    baselineAgent.business_logic_model_id !== editedAgent.business_logic_model_id ||
    (baselineAgent.prompt_template_id ?? 0) !== (editedAgent.prompt_template_id ?? 0) ||
    (baselineAgent.prompt_template_name || "system_default") !== (editedAgent.prompt_template_name || "system_default") ||
    JSON.stringify(normalizeArray(baselineAgent.group_ids ?? [])) !==
      JSON.stringify(normalizeArray(editedAgent.group_ids ?? [])) ||
    JSON.stringify(normalizeArray(baselineAgent.sub_agent_id_list ?? [])) !==
      JSON.stringify(normalizeArray(editedAgent.sub_agent_id_list ?? [])) ||
    JSON.stringify(normalizeArray(baselineAgent.external_sub_agent_id_list ?? [])) !==
      JSON.stringify(normalizeArray(editedAgent.external_sub_agent_id_list ?? [])) ||
    isToolsDirty(baselineAgent.tools, editedAgent.tools) ||
    isSkillsDirty(baselineAgent.skills, editedAgent.skills) ||
    baselineAgent.ingroup_permission !== editedAgent.ingroup_permission
  );
};

export const useAgentConfigStore = create<AgentConfigStoreState>((set, get) => ({
  currentAgentId: null,
  currentAgentPermission: null,
  baselineAgent: null,
  editedAgent: createEmptyEditableAgent(),
  hasUnsavedChanges: false,
  isCreatingMode: false,
  isGenerating: false,
  defaultLlmConfig: null,
  forceRefreshKey: 0,

  isReadOnly: () => {
    const { isCreatingMode, currentAgentId, currentAgentPermission } = get();
    if (isCreatingMode === false && currentAgentId === null) return true;
    if (isCreatingMode) return false;
    return currentAgentPermission === 'READ_ONLY';
  },

  setCurrentAgent: (agent) => {
    const agentId = agent ? parseInt(agent.id) : null;
    const baselineAgent = agent ? toEditable(agent) : null;
    const { defaultLlmConfig } = get();
    let editedAgent = baselineAgent ? { ...baselineAgent } : createEmptyEditableAgent(defaultLlmConfig ?? undefined);

    // Check if there's a pending generation cache to restore
    if (agentId !== null && baselineAgent) {
      const cached = getAgentGenerationCache(agentId);
      if (cached && !cached.isGenerating) {
        // Generation completed while user was away, restore the cached data to editedAgent
        const cacheUpdates: Partial<EditableAgent> = {};
        
        if (cached.dutyPrompt) cacheUpdates.duty_prompt = cached.dutyPrompt;
        if (cached.constraintPrompt) cacheUpdates.constraint_prompt = cached.constraintPrompt;
        if (cached.fewShotsPrompt) cacheUpdates.few_shots_prompt = cached.fewShotsPrompt;
        
        // Only restore agent metadata if not already set in baseline
        if (cached.agentName && !editedAgent.name) cacheUpdates.name = cached.agentName;
        if (cached.agentDisplayName && !editedAgent.display_name) cacheUpdates.display_name = cached.agentDisplayName;
        if (cached.agentDescription && !editedAgent.description) cacheUpdates.description = cached.agentDescription;
        editedAgent = { ...editedAgent, ...cacheUpdates };
      }
    }

    set({
      currentAgentId: agentId,
      currentAgentPermission: agent ? ((agent as any).permission ?? null) : null,
      baselineAgent,
      editedAgent,
      hasUnsavedChanges: isDirty(baselineAgent, editedAgent),
      isCreatingMode: false,
      forceRefreshKey: 0,
    });
  },

  enterCreateMode: () => {
    const { defaultLlmConfig } = get();
    set({
      currentAgentId: null,
      currentAgentPermission: "EDIT",
      baselineAgent: null,
      editedAgent: createEmptyEditableAgent(defaultLlmConfig ?? undefined),
      hasUnsavedChanges: false,
      isCreatingMode: true,
      forceRefreshKey: 0,
    });
  },

  triggerForceRefresh: () => {
    set((state) => ({ forceRefreshKey: state.forceRefreshKey + 1 }));
  },

  updateTools: (tools) => {
    set((state) => {
      const editedAgent = { ...state.editedAgent, tools: [...tools] };
      const hasUnsavedChanges = isDirty(state.baselineAgent, editedAgent);
      return { editedAgent, hasUnsavedChanges };
    });
  },

  updateSkills: (skills) => {
    set((state) => {
      const editedAgent = { ...state.editedAgent, skills: [...skills] };
      const hasUnsavedChanges = isDirty(state.baselineAgent, editedAgent);
      return { editedAgent, hasUnsavedChanges };
    });
  },

  updateSubAgentIds: (ids) => {
    const nextIds = normalizeArray(ids);
    set((state) => {
      const editedAgent = { ...state.editedAgent, sub_agent_id_list: nextIds };
      const hasUnsavedChanges = isDirty(state.baselineAgent, editedAgent);
      return { editedAgent, hasUnsavedChanges };
    });
  },

  updateExternalSubAgentIds: (ids) => {
    set((state) => {
      const editedAgent = { ...state.editedAgent, external_sub_agent_id_list: ids };
      const hasUnsavedChanges = isDirty(state.baselineAgent, editedAgent);
      return { editedAgent, hasUnsavedChanges };
    });
  },

  updateAgentConfig: (payload) => {
    set((state) => {
      const editedAgent = { ...state.editedAgent, ...payload };
      const hasUnsavedChanges = isDirty(state.baselineAgent, editedAgent);
      return { editedAgent, hasUnsavedChanges };
    });
  },

  markAsSaved: () => {
    const { editedAgent } = get();
    set({
      baselineAgent: { ...editedAgent },
      hasUnsavedChanges: false,
    });
  },

  discardChanges: () => {
    set((state) => {
      const baselineAgent = state.baselineAgent;
      const { defaultLlmConfig } = state;
      const editedAgent = baselineAgent ? { ...baselineAgent } : createEmptyEditableAgent(defaultLlmConfig ?? undefined);
      return {
        editedAgent,
        hasUnsavedChanges: false,
      };
    });
  },

  setIsGenerating: (value: boolean) => {
    set({ isGenerating: value });
  },

  reset: () => {
    const { defaultLlmConfig } = get();
    set({
      currentAgentId: null,
      currentAgentPermission: null,
      baselineAgent: null,
      editedAgent: createEmptyEditableAgent(defaultLlmConfig ?? undefined),
      hasUnsavedChanges: false,
      isCreatingMode: false,
      isGenerating: false,
      forceRefreshKey: 0,
    });
  },

  setDefaultLlmConfig: (config) => {
    set({ defaultLlmConfig: config });
  },

  getCurrentAgent: () => {
    return get().baselineAgent;
  },
}));

