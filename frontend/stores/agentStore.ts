import { create } from "zustand";

import {
  searchToolConfig,
  updateAgentInfo,
  updateToolConfig,
} from "@/services/agentConfigService";
import type { EditableAgent } from "@/stores/agentConfigStore";
import type { Tool } from "@/types/agentConfig";

export type AgentDraft = EditableAgent;
export type AgentDraftPatch = Partial<AgentDraft>;

export interface AgentSaveTask {
  agentId: number;
  patch: AgentDraftPatch;
}

interface AgentStoreState {
  agentId: number | null;
  isReadOnly: boolean;
  editedAgent: AgentDraft | null;
  savedAgent: AgentDraft | null;
  queue: AgentSaveTask[];
  isSaving: boolean;
  saveError: string | null;

  initialize: (agentId: number, agent: AgentDraft, isReadOnly: boolean) => void;
  updateDraft: (patch: AgentDraftPatch) => void;
  flushDraft: () => void;
  updateAgentConfig: (patch: AgentDraftPatch) => void;
  updateTools: (tools: Tool[]) => void;
  updateSkills: (skills: AgentDraft["skills"]) => void;
  updateSubAgentIds: (ids: number[]) => void;
  updateSubAgentRelations: (
    relations: AgentDraft["sub_agent_relations"]
  ) => void;
  updateExternalSubAgentIds: (ids: number[]) => void;
  waitForIdle: () => Promise<void>;
  clearSaveError: () => void;
  reset: () => void;
}

const cloneDraft = <T>(value: T): T => structuredClone(value);

const mergeDraft = (
  agent: AgentDraft | null,
  patch: AgentDraftPatch
): AgentDraft | null => (agent ? { ...agent, ...patch } : null);

const DRAFT_SAVE_DEBOUNCE_MS = 500;
let pendingDraftPatch: AgentDraftPatch = {};
let draftSaveTimer: ReturnType<typeof setTimeout> | null = null;

const clearPendingDraftSave = () => {
  if (draftSaveTimer) {
    clearTimeout(draftSaveTimer);
    draftSaveTimer = null;
  }
  pendingDraftPatch = {};
};

const applyQueuedPatches = (
  savedAgent: AgentDraft | null,
  queue: AgentSaveTask[]
): AgentDraft | null =>
  queue.reduce(
    (draft, task) => mergeDraft(draft, task.patch),
    savedAgent ? cloneDraft(savedAgent) : null
  );

const toAgentPayload = (agentId: number, patch: AgentDraftPatch) => ({
  agent_id: agentId,
  ...(patch.name !== undefined ? { name: patch.name } : {}),
  ...(patch.display_name !== undefined
    ? { display_name: patch.display_name }
    : {}),
  ...(patch.description !== undefined
    ? { description: patch.description }
    : {}),
  ...(patch.author !== undefined ? { author: patch.author } : {}),
  ...(patch.group_ids !== undefined ? { group_ids: patch.group_ids } : {}),
  ...(patch.model_ids !== undefined ? { model_ids: patch.model_ids } : {}),
  ...(patch.max_step !== undefined ? { max_steps: patch.max_step } : {}),
  ...(patch.requested_output_tokens !== undefined
    ? { requested_output_tokens: patch.requested_output_tokens }
    : {}),
  ...(patch.is_main_agent !== undefined
    ? { is_main_agent: patch.is_main_agent }
    : {}),
  ...(patch.provide_run_summary !== undefined
    ? { provide_run_summary: patch.provide_run_summary }
    : {}),
  ...(patch.enable_a2a !== undefined ? { enable_a2a: patch.enable_a2a } : {}),
  ...(patch.enable_context_manager !== undefined
    ? { enable_context_manager: patch.enable_context_manager }
    : {}),
  ...(patch.verification_config !== undefined
    ? { verification_config: patch.verification_config }
    : {}),
  ...(patch.business_description !== undefined
    ? { business_description: patch.business_description }
    : {}),
  ...(patch.business_logic_model_name !== undefined
    ? { business_logic_model_name: patch.business_logic_model_name }
    : {}),
  ...(patch.business_logic_model_id !== undefined
    ? { business_logic_model_id: patch.business_logic_model_id }
    : {}),
  ...(patch.prompt_template_id !== undefined
    ? { prompt_template_id: patch.prompt_template_id }
    : {}),
  ...(patch.prompt_template_name !== undefined
    ? { prompt_template_name: patch.prompt_template_name }
    : {}),
  ...(patch.duty_prompt !== undefined
    ? { duty_prompt: patch.duty_prompt }
    : {}),
  ...(patch.constraint_prompt !== undefined
    ? { constraint_prompt: patch.constraint_prompt }
    : {}),
  ...(patch.few_shots_prompt !== undefined
    ? { few_shots_prompt: patch.few_shots_prompt }
    : {}),
  ...(patch.tools !== undefined
    ? {
        enabled_tool_ids: patch.tools
          .filter((tool) => tool.is_available !== false)
          .map((tool) => Number(tool.id))
          .filter(Number.isFinite),
      }
    : {}),
  ...(patch.skills !== undefined
    ? {
        enabled_skill_ids: patch.skills
          .map((skill) => Number(skill.skill_id))
          .filter(Number.isFinite),
        skill_instances: patch.skills
          .map((skill) => ({
            skill_id: Number(skill.skill_id),
            enabled: true,
            config_values: skill.config_values ?? {},
          }))
          .filter((skill) => Number.isFinite(skill.skill_id)),
      }
    : {}),
  ...(patch.sub_agent_id_list !== undefined
    ? { related_agent_ids: patch.sub_agent_id_list }
    : {}),
  ...(patch.sub_agent_relations !== undefined
    ? {
        related_agents: patch.sub_agent_relations.map((relation) => ({
          agent_id: relation.agent_id,
          version_no: relation.version_no ?? 0,
        })),
      }
    : {}),
  ...(patch.external_sub_agent_id_list !== undefined
    ? { related_external_agent_ids: patch.external_sub_agent_id_list }
    : {}),
  ...(patch.ingroup_permission !== undefined
    ? { ingroup_permission: patch.ingroup_permission }
    : {}),
  ...(patch.greeting_message !== undefined
    ? { greeting_message: patch.greeting_message }
    : {}),
  ...(patch.example_questions !== undefined
    ? { example_questions: patch.example_questions }
    : {}),
});

const toToolParams = (tool: Tool): Record<string, unknown> =>
  (tool.initParams ?? []).reduce<Record<string, unknown>>(
    (params, parameter) => {
      if (parameter.value !== undefined && parameter.value !== null) {
        params[parameter.name] = parameter.value;
      }
      return params;
    },
    {}
  );

async function persistToolChanges(
  agentId: number,
  currentTools: Tool[],
  savedTools: Tool[]
): Promise<void> {
  const currentToolIds = new Set(currentTools.map((tool) => Number(tool.id)));

  for (const tool of currentTools) {
    const result = await updateToolConfig(
      Number(tool.id),
      agentId,
      toToolParams(tool),
      true
    );
    if (!result.success) {
      throw new Error(result.message);
    }
  }

  for (const tool of savedTools) {
    const toolId = Number(tool.id);
    if (currentToolIds.has(toolId)) {
      continue;
    }

    const existingConfig = await searchToolConfig(toolId, agentId);
    const result = await updateToolConfig(
      toolId,
      agentId,
      existingConfig.data?.params ?? {},
      false
    );
    if (!result.success) {
      throw new Error(result.message);
    }
  }
}

async function processSaveQueue(): Promise<void> {
  if (useAgentStore.getState().isSaving) {
    return;
  }

  while (true) {
    const task = useAgentStore.getState().queue[0];
    if (!task) {
      return;
    }

    useAgentStore.setState({ isSaving: true, saveError: null });

    try {
      const result = await updateAgentInfo(
        toAgentPayload(task.agentId, task.patch)
      );
      if (!result.success) {
        throw new Error(result.message);
      }

      const savedAgent = useAgentStore.getState().savedAgent;
      if (task.patch.tools !== undefined) {
        await persistToolChanges(
          task.agentId,
          task.patch.tools,
          savedAgent?.tools ?? []
        );
      }

      const currentState = useAgentStore.getState();
      if (
        currentState.agentId !== task.agentId ||
        currentState.queue[0] !== task
      ) {
        return;
      }

      useAgentStore.setState((state) => ({
        savedAgent: mergeDraft(state.savedAgent, task.patch),
        queue: state.queue.slice(1),
        isSaving: false,
      }));
    } catch (error) {
      const currentState = useAgentStore.getState();
      if (
        currentState.agentId !== task.agentId ||
        currentState.queue[0] !== task
      ) {
        return;
      }

      useAgentStore.setState((state) => {
        const queue = state.queue.slice(1);
        return {
          editedAgent: mergeDraft(
            applyQueuedPatches(state.savedAgent, queue),
            pendingDraftPatch
          ),
          queue,
          isSaving: false,
          saveError:
            error instanceof Error
              ? error.message
              : "Failed to save agent changes",
        };
      });
    }
  }
}

export const useAgentStore = create<AgentStoreState>((set) => {
  const enqueue = (patch: AgentDraftPatch) => {
    const { agentId, isReadOnly } = useAgentStore.getState();
    if (agentId === null || isReadOnly) {
      return;
    }

    const task: AgentSaveTask = { agentId, patch: cloneDraft(patch) };
    set((state) => ({
      editedAgent: mergeDraft(state.editedAgent, task.patch),
      queue: [...state.queue, task],
      saveError: null,
    }));
    void processSaveQueue();
  };

  return {
    agentId: null,
    isReadOnly: true,
    editedAgent: null,
    savedAgent: null,
    queue: [],
    isSaving: false,
    saveError: null,

    initialize: (agentId, agent, isReadOnly) => {
      clearPendingDraftSave();
      set({
        agentId,
        isReadOnly,
        editedAgent: cloneDraft(agent),
        savedAgent: cloneDraft(agent),
        queue: [],
        isSaving: false,
        saveError: null,
      });
    },

    updateDraft: (patch) => {
      const draftPatch = cloneDraft(patch);
      pendingDraftPatch = { ...pendingDraftPatch, ...draftPatch };

      set((state) => ({
        editedAgent: mergeDraft(state.editedAgent, draftPatch),
        saveError: null,
      }));

      if (draftSaveTimer) {
        clearTimeout(draftSaveTimer);
      }
      draftSaveTimer = setTimeout(() => {
        draftSaveTimer = null;
        useAgentStore.getState().flushDraft();
      }, DRAFT_SAVE_DEBOUNCE_MS);
    },
    flushDraft: () => {
      if (draftSaveTimer) {
        clearTimeout(draftSaveTimer);
        draftSaveTimer = null;
      }

      const patch = pendingDraftPatch;
      pendingDraftPatch = {};
      if (Object.keys(patch).length > 0) {
        enqueue(patch);
      }
    },
    updateAgentConfig: enqueue,
    updateTools: (tools) => enqueue({ tools }),
    updateSkills: (skills) => enqueue({ skills }),
    updateSubAgentIds: (sub_agent_id_list) => enqueue({ sub_agent_id_list }),
    updateSubAgentRelations: (sub_agent_relations) =>
      enqueue({ sub_agent_relations }),
    updateExternalSubAgentIds: (external_sub_agent_id_list) =>
      enqueue({ external_sub_agent_id_list }),
    waitForIdle: () => {
      useAgentStore.getState().flushDraft();
      return new Promise((resolve) => {
        if (
          !useAgentStore.getState().isSaving &&
          useAgentStore.getState().queue.length === 0
        ) {
          resolve();
          return;
        }

        const unsubscribe = useAgentStore.subscribe((state) => {
          if (!state.isSaving && state.queue.length === 0) {
            unsubscribe();
            resolve();
          }
        });
      });
    },
    clearSaveError: () => set({ saveError: null }),
    reset: () => {
      clearPendingDraftSave();
      set({
        agentId: null,
        isReadOnly: true,
        editedAgent: null,
        savedAgent: null,
        queue: [],
        isSaving: false,
        saveError: null,
      });
    },
  };
});
