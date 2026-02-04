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

import { Agent, Tool, AgentBusinessInfo, AgentProfileInfo } from "@/types/agentConfig";

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
  | "sub_agent_id_list"
  | "group_ids"
>;

interface AgentConfigStoreState {
  currentAgentId: number | null;
  /**
   * Per-agent permission from /agent/list.
   * - EDIT: editable
   * - READ_ONLY: read-only
   * null: unknown / not selected
   */
  currentAgentPermission: "EDIT" | "READ_ONLY" | null;
  baselineAgent: EditableAgent | null;
  editedAgent: EditableAgent;
  hasUnsavedChanges: boolean;
  isCreatingMode: boolean; // true when user is in create mode, even if currentAgentId is null

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
   * Update tools (selected tools).
   */
  updateTools: (tools: Tool[]) => void;

  /**
   * Update sub_agent_id_list (Component B).
   */
  updateSubAgentIds: (ids: number[]) => void;

  /**
   * Update business info (Component C top):
   * business_description, business_logic_model_id, business_logic_model_name
   */
  updateBusinessInfo: (payload: AgentBusinessInfo) => void;

  /**
   * Update profile/info fields (Component C bottom):
   * name, display_name, author, model, model_id,
   * max_step, description, duty_prompt, constraint_prompt,
   * few_shots_prompt
   */
  updateProfileInfo: (payload: AgentProfileInfo) => void;

  /**
   * Mark changes as saved: move edited -> baseline, clear hasUnsavedChanges.
   */
  markAsSaved: () => void;

  /**
   * Discard changes: revert edited to baseline.
   */
  discardChanges: () => void;

  /**
   * Reset all state (optional).
   */
  reset: () => void;

  /**
   * Get the current baseline editable agent (null = create or initial state).
   * Use isCreatingMode to distinguish between initial state and create mode.
   */
  getCurrentAgent: () => EditableAgent | null;
}

const emptyEditableAgent: EditableAgent = {
  name: "",
  display_name: "",
  description: "",
  author: "",
  model: "",
  model_id: 0,
  max_step: 0,
  provide_run_summary: false,
  tools: [],
  duty_prompt: "",
  constraint_prompt: "",
  few_shots_prompt: "",
  business_description: "",
  business_logic_model_name: "",
  business_logic_model_id: 0,
  sub_agent_id_list: [],
  group_ids: [],
};

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
        duty_prompt: agent.duty_prompt || "",
        constraint_prompt: agent.constraint_prompt || "",
        few_shots_prompt: agent.few_shots_prompt || "",
        business_description: agent.business_description || "",
        business_logic_model_name: agent.business_logic_model_name || "",
        business_logic_model_id: agent.business_logic_model_id || 0,
        sub_agent_id_list: agent.sub_agent_id_list || [],
        group_ids: agent.group_ids || [],
      }
    : { ...emptyEditableAgent };

const normalizeArray = (arr: number[]) =>
  Array.from(new Set((arr ?? []).map((n) => Number(n)).filter((n) => !isNaN(n)))).sort(
    (a, b) => a - b
  );

// Dirty check helpers for specific field groups
const isBusinessInfoDirty = (baselineAgent: EditableAgent | null, editedAgent: EditableAgent): boolean => {
  if (!baselineAgent) {
    return (
      editedAgent.business_description !== "" ||
      editedAgent.business_logic_model_name !== "" ||
      editedAgent.business_logic_model_id !== 0
    );
  }
  return (
    baselineAgent.business_description !== editedAgent.business_description ||
    baselineAgent.business_logic_model_name !== editedAgent.business_logic_model_name ||
    baselineAgent.business_logic_model_id !== editedAgent.business_logic_model_id
  );
};

const isProfileInfoDirty = (baselineAgent: EditableAgent | null, editedAgent: EditableAgent): boolean => {
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
      normalizeArray(editedAgent.group_ids || []).length > 0
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
    JSON.stringify(normalizeArray(baselineAgent.group_ids ?? [])) !==
      JSON.stringify(normalizeArray(editedAgent.group_ids ?? []))
  );
};

const isToolsDirty = (baselineAgent: EditableAgent | null, editedAgent: EditableAgent): boolean => {
  if (!baselineAgent) {
    return editedAgent.tools.length > 0;
  }
  return JSON.stringify(baselineAgent.tools) !== JSON.stringify(editedAgent.tools);
};

const isSubAgentIdsDirty = (baselineAgent: EditableAgent | null, editedAgent: EditableAgent): boolean => {
  if (!baselineAgent) {
    return normalizeArray(editedAgent.sub_agent_id_list || []).length > 0;
  }
  return JSON.stringify(normalizeArray(baselineAgent.sub_agent_id_list ?? [])) !==
    JSON.stringify(normalizeArray(editedAgent.sub_agent_id_list ?? []));
};

export const useAgentConfigStore = create<AgentConfigStoreState>((set, get) => ({
  currentAgentId: null,
  currentAgentPermission: null,
  baselineAgent: null,
  editedAgent: { ...emptyEditableAgent },
  hasUnsavedChanges: false,
  isCreatingMode: false,

  setCurrentAgent: (agent) => {
    const baselineAgent = agent ? toEditable(agent) : null;
    const editedAgent = baselineAgent ? { ...baselineAgent } : { ...emptyEditableAgent };
    set({
      currentAgentId: agent ? parseInt(agent.id) : null,
      currentAgentPermission: agent ? ((agent as any).permission ?? null) : null,
      baselineAgent,
      editedAgent,
      hasUnsavedChanges: false,
      isCreatingMode: false, // Exit create mode when selecting an agent
    });
  },

  enterCreateMode: () => {
    set({
      currentAgentId: null,
      currentAgentPermission: "EDIT",
      baselineAgent: null,
      editedAgent: { ...emptyEditableAgent },
      hasUnsavedChanges: false,
      isCreatingMode: true,
    });
  },

  updateTools: (tools) => {
    set((state) => {
      const editedAgent = { ...state.editedAgent, tools: [...tools] };
      // If there are already unsaved changes, keep it true and skip recalculation.
      // Only when state is clean do we need to check whether tools changed.
      const hasUnsavedChanges = state.hasUnsavedChanges
        ? true
        : isToolsDirty(state.baselineAgent, editedAgent);
      return {
        editedAgent,
        hasUnsavedChanges,
      };
    });
  },

  updateSubAgentIds: (ids) => {
    const nextIds = normalizeArray(ids);
    set((state) => {
      const editedAgent = { ...state.editedAgent, sub_agent_id_list: nextIds };
      // If there are already unsaved changes, keep it true and skip recalculation.
      // Only when state is clean do we need to check whether sub-agent IDs changed.
      const hasUnsavedChanges = state.hasUnsavedChanges
        ? true
        : isSubAgentIdsDirty(state.baselineAgent, editedAgent);
      return {
        editedAgent,
        hasUnsavedChanges,
      };
    });
  },

  updateBusinessInfo: (payload) => {
    set((state) => {
      const editedAgent = { ...state.editedAgent, ...payload };
      // If there are already unsaved changes, keep it true and skip recalculation.
      // Only when state is clean do we need to check whether business info changed.
      const hasUnsavedChanges = state.hasUnsavedChanges
        ? true
        : isBusinessInfoDirty(state.baselineAgent, editedAgent);
      return {
        editedAgent,
        hasUnsavedChanges,
      };
    });
  },

  updateProfileInfo: (payload) => {
    set((state) => {
      const editedAgent = { ...state.editedAgent, ...payload };
      // If there are already unsaved changes, keep it true and skip recalculation.
      // Only when state is clean do we need to check whether profile info changed.
      const hasUnsavedChanges = state.hasUnsavedChanges
        ? true
        : isProfileInfoDirty(state.baselineAgent, editedAgent);
      return {
        editedAgent,
        hasUnsavedChanges,
      };
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
      const editedAgent = baselineAgent ? { ...baselineAgent } : { ...emptyEditableAgent };
      return {
        editedAgent,
        hasUnsavedChanges: false,
      };
    });
  },

  reset: () => {
    set({
      currentAgentId: null,
      currentAgentPermission: null,
      baselineAgent: null,
      editedAgent: { ...emptyEditableAgent },
      hasUnsavedChanges: false,
      isCreatingMode: false,
    });
  },

  getCurrentAgent: () => {
    return get().baselineAgent;
  },
}));

