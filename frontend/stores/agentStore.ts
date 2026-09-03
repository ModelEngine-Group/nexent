import { create } from "zustand";

import { safeStringify } from "@/lib/utils";
import {
  searchToolConfig,
  updateAgentInfo,
  updateToolConfig,
} from "@/services/agentConfigService";
import type { Agent, Skill, Tool } from "@/types/agentConfig";
import {
  AIDP_NON_PERSISTED_PARAM_NAMES,
  isAidpManagedKnowledgeTool,
  isManagedKnowledgeTool,
} from "@/lib/managedKnowledgeTools";

export type AgentDraft = Pick<
  Agent,
  | "name"
  | "display_name"
  | "description"
  | "author"
  | "created_by"
  | "model"
  | "model_ids"
  | "model_names"
  | "unavailable_reasons"
  | "max_step"
  | "requested_output_tokens"
  | "is_main_agent"
  | "provide_run_summary"
  | "allow_chat_metadata"
  | "enable_context_manager"
  | "is_a2a"
  | "verification_config"
  | "tools"
  | "duty_prompt"
  | "constraint_prompt"
  | "few_shots_prompt"
  | "business_logic_model_name"
  | "business_logic_model_id"
  | "prompt_template_id"
  | "prompt_template_name"
  | "sub_agent_id_list"
  | "sub_agent_relations"
  | "external_sub_agent_id_list"
  | "group_ids"
  | "ingroup_permission"
  | "greeting_message"
  | "example_questions"
  | "icon_url"
> & { skills: Skill[] };
export type AgentDraftPatch = Partial<AgentDraft>;

export interface AgentSaveTask {
  agentId: number;
  patch: AgentDraftPatch;
}

export interface PersistedResourceBindings {
  tools?: Tool[];
  skills?: Skill[];
}

interface AgentStoreState {
  agentId: number | null;
  currentAgentId: number | null;
  isReadOnly: boolean;
  editedAgent: AgentDraft | null;
  savedAgent: AgentDraft | null;
  serverSnapshotRevision: number;
  queue: AgentSaveTask[];
  isGenerating: boolean;
  saveError: string | null;
  lastSaveFailed: boolean;
  defaultLlmConfig: {
    id: number | null;
    name: string;
    displayName: string;
  } | null;

  initialize: (agent: Agent) => void;
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
  setDefaultLlmConfig: (
    config: { id: number | null; name: string; displayName: string } | null
  ) => void;
  setIsGenerating: (value: boolean) => void;
  applyPersistedResourceBindings: (
    agentId: number,
    resources: PersistedResourceBindings
  ) => boolean;
  replaceServerSnapshot: (agentId: number, agent: Agent) => boolean;
  waitForIdle: () => Promise<boolean>;
  clearSaveError: () => void;
  reset: () => void;
}

const toDraft = (agent: Agent): AgentDraft => ({
  name: agent.name,
  display_name: agent.display_name || "",
  description: agent.description || "",
  author: agent.author || "",
  created_by: agent.created_by ?? null,
  model: agent.model || "",
  model_ids: agent.model_ids || [],
  model_names: agent.model_names || [],
  unavailable_reasons: agent.unavailable_reasons || [],
  max_step: agent.max_step,
  requested_output_tokens: agent.requested_output_tokens ?? null,
  is_main_agent: agent.is_main_agent ?? true,
  provide_run_summary: agent.provide_run_summary,
  allow_chat_metadata: agent.allow_chat_metadata ?? false,
  enable_context_manager: agent.enable_context_manager,
  is_a2a: agent.is_a2a,
  verification_config: agent.verification_config,
  tools: [...(agent.tools || [])],
  skills: [...(agent.skills || [])],
  duty_prompt: agent.duty_prompt || "",
  constraint_prompt: agent.constraint_prompt || "",
  few_shots_prompt: agent.few_shots_prompt || "",
  business_logic_model_name: agent.business_logic_model_name || "",
  business_logic_model_id: agent.business_logic_model_id || 0,
  prompt_template_id: agent.prompt_template_id ?? 0,
  prompt_template_name: agent.prompt_template_name || "system_default",
  sub_agent_id_list: agent.sub_agent_id_list || [],
  sub_agent_relations: agent.sub_agent_relations || [],
  external_sub_agent_id_list: agent.external_sub_agent_id_list || [],
  group_ids: agent.group_ids || [],
  ingroup_permission: agent.ingroup_permission || "READ_ONLY",
  greeting_message: agent.greeting_message || "",
  example_questions: agent.example_questions || [],
  icon_url: agent.icon_url,
});

const cloneDraft = <T>(value: T): T => structuredClone(value);

const mergeDraft = (
  agent: AgentDraft | null,
  patch: AgentDraftPatch
): AgentDraft | null => (agent ? { ...agent, ...patch } : null);

const mergeResourcesById = <T>(
  current: T[],
  persisted: T[],
  getId: (resource: T) => number
): T[] => {
  const merged = new Map(
    current.map((resource) => [getId(resource), cloneDraft(resource)])
  );
  persisted.forEach((resource) => {
    const resourceId = getId(resource);
    const existing = merged.get(resourceId);
    merged.set(
      resourceId,
      existing ? { ...existing, ...cloneDraft(resource) } : cloneDraft(resource)
    );
  });
  return Array.from(merged.values());
};

const mergePersistedResources = (
  draft: AgentDraft | null,
  resources: PersistedResourceBindings
): AgentDraft | null => {
  if (!draft) return null;
  return {
    ...draft,
    ...(resources.tools
      ? {
          tools: mergeResourcesById(draft.tools, resources.tools, (tool) =>
            Number(tool.id)
          ),
        }
      : {}),
    ...(resources.skills
      ? {
          skills: mergeResourcesById(draft.skills, resources.skills, (skill) =>
            Number(skill.skill_id)
          ),
        }
      : {}),
  };
};

const DRAFT_SAVE_DEBOUNCE_MS = 500;
let pendingDraftPatch: AgentDraftPatch = {};
let draftSaveTimer: ReturnType<typeof setTimeout> | null = null;
let saveQueue: AgentSaveTask[] = [];
let saveQueueProcessing = false;
let idleWaiters: Array<(success: boolean) => void> = [];

const resolveIdleWaiters = () => {
  if (saveQueueProcessing || saveQueue.length > 0) {
    return;
  }

  const success = !useAgentStore.getState().lastSaveFailed;
  const waiters = idleWaiters;
  idleWaiters = [];
  waiters.forEach((resolve) => resolve(success));
};

const hasPendingSaveWork = (): boolean =>
  saveQueueProcessing ||
  saveQueue.length > 0 ||
  draftSaveTimer !== null ||
  Object.keys(pendingDraftPatch).length > 0;

const canApplyPersistedState = (
  state: AgentStoreState,
  agentId: number
): boolean =>
  state.agentId === agentId &&
  state.currentAgentId === agentId &&
  state.editedAgent !== null &&
  state.savedAgent !== null &&
  !hasPendingSaveWork();

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
  ...(patch.icon_url !== undefined ? { icon_url: patch.icon_url } : {}),
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
  ...(patch.allow_chat_metadata !== undefined
    ? { allow_chat_metadata: patch.allow_chat_metadata }
    : {}),
  ...(patch.is_a2a !== undefined ? { is_a2a: patch.is_a2a } : {}),
  ...(patch.enable_context_manager !== undefined
    ? { enable_context_manager: patch.enable_context_manager }
    : {}),
  ...(patch.verification_config !== undefined
    ? { verification_config: patch.verification_config }
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
          .filter(
            (tool) =>
              tool.is_available !== false || isManagedKnowledgeTool(tool)
          )
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
      if (
        isAidpManagedKnowledgeTool(tool) &&
        AIDP_NON_PERSISTED_PARAM_NAMES.has(parameter.name)
      ) {
        return params;
      }
      if (parameter.value !== undefined && parameter.value !== null) {
        params[parameter.name] = parameter.value;
      }
      return params;
    },
    {}
  );

const areToolParamsEqual = (left: Tool, right: Tool): boolean => {
  const leftParams = toToolParams(left);
  const rightParams = toToolParams(right);
  const leftKeys = Object.keys(leftParams).sort();
  const rightKeys = Object.keys(rightParams).sort();

  if (leftKeys.length !== rightKeys.length) return false;
  return leftKeys.every((key, index) => {
    if (key !== rightKeys[index]) return false;

    const leftValue = safeStringify(leftParams[key]);
    const rightValue = safeStringify(rightParams[key]);
    return leftValue !== null && leftValue === rightValue;
  });
};

async function persistToolChanges(
  agentId: number,
  currentTools: Tool[],
  savedTools: Tool[]
): Promise<void> {
  const currentToolIds = new Set(currentTools.map((tool) => Number(tool.id)));
  const savedToolsById = new Map(
    savedTools.map((tool) => [Number(tool.id), tool])
  );

  for (const tool of currentTools) {
    if (tool.is_available === false) {
      continue;
    }
    const savedTool = savedToolsById.get(Number(tool.id));
    if (savedTool && areToolParamsEqual(tool, savedTool)) {
      continue;
    }

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
    if (tool.is_available === false) {
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
  if (saveQueueProcessing) {
    return;
  }

  saveQueueProcessing = true;
  let drainHadFailure = false;

  try {
    while (true) {
      const task = saveQueue[0];
      if (!task) {
        return;
      }

      useAgentStore.setState({ saveError: null });

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
        if (currentState.agentId !== task.agentId || saveQueue[0] !== task) {
          return;
        }

        saveQueue = saveQueue.slice(1);
        useAgentStore.setState((state) => ({
          savedAgent: mergeDraft(state.savedAgent, task.patch),
          lastSaveFailed:
            drainHadFailure || saveQueue.length > 0
              ? state.lastSaveFailed
              : false,
        }));
      } catch (error) {
        drainHadFailure = true;
        const currentState = useAgentStore.getState();
        if (currentState.agentId !== task.agentId || saveQueue[0] !== task) {
          return;
        }

        saveQueue = saveQueue.slice(1);
        useAgentStore.setState((state) => ({
          editedAgent: mergeDraft(
            applyQueuedPatches(state.savedAgent, saveQueue),
            pendingDraftPatch
          ),
          lastSaveFailed: true,
          saveError:
            error instanceof Error
              ? error.message
              : "Failed to save agent changes",
        }));
      }
    }
  } finally {
    saveQueueProcessing = false;
    resolveIdleWaiters();
    if (saveQueue.length > 0) {
      void processSaveQueue();
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
    saveQueue = [...saveQueue, task];
    set((state) => ({
      editedAgent: mergeDraft(state.editedAgent, task.patch),
      saveError: null,
    }));
    void processSaveQueue();
  };

  return {
    agentId: null,
    currentAgentId: null,
    isReadOnly: true,
    editedAgent: null,
    savedAgent: null,
    serverSnapshotRevision: 0,
    queue: [],
    isGenerating: false,
    saveError: null,
    lastSaveFailed: false,
    defaultLlmConfig: null,

    initialize: (agent) => {
      clearPendingDraftSave();
      saveQueue = [];
      const agentId = Number(agent.id);
      const draft = toDraft(agent);
      set((state) => ({
        agentId,
        currentAgentId: agentId,
        isReadOnly: agent.permission === "READ_ONLY",
        editedAgent: cloneDraft(draft),
        savedAgent: cloneDraft(draft),
        serverSnapshotRevision: state.serverSnapshotRevision + 1,
        isGenerating: false,
        saveError: null,
        lastSaveFailed: false,
      }));
    },

    updateDraft: (patch) => {
      const draftPatch = cloneDraft(patch);

      set((state) => ({
        editedAgent: mergeDraft(state.editedAgent, draftPatch),
        saveError: null,
      }));

      pendingDraftPatch = { ...pendingDraftPatch, ...draftPatch };

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
    setDefaultLlmConfig: (defaultLlmConfig) => set({ defaultLlmConfig }),
    setIsGenerating: (isGenerating) => set({ isGenerating }),
    applyPersistedResourceBindings: (agentId, resources) => {
      let applied = false;
      set((state) => {
        if (!canApplyPersistedState(state, agentId)) return state;
        applied = true;
        return {
          editedAgent: mergePersistedResources(state.editedAgent, resources),
          savedAgent: mergePersistedResources(state.savedAgent, resources),
          saveError: null,
          lastSaveFailed: false,
        };
      });
      return applied;
    },
    replaceServerSnapshot: (agentId, agent) => {
      if (Number(agent.id) !== agentId) return false;

      const draft = toDraft(agent);
      let replaced = false;
      set((state) => {
        if (!canApplyPersistedState(state, agentId)) return state;
        replaced = true;
        return {
          isReadOnly: agent.permission === "READ_ONLY",
          editedAgent: cloneDraft(draft),
          savedAgent: cloneDraft(draft),
          serverSnapshotRevision: state.serverSnapshotRevision + 1,
          saveError: null,
          lastSaveFailed: false,
        };
      });
      return replaced;
    },
    waitForIdle: () => {
      useAgentStore.getState().flushDraft();
      return new Promise((resolve) => {
        if (!saveQueueProcessing && saveQueue.length === 0) {
          resolve(!useAgentStore.getState().lastSaveFailed);
          return;
        }

        idleWaiters.push(resolve);
      });
    },
    clearSaveError: () => set({ saveError: null }),
    reset: () => {
      clearPendingDraftSave();
      saveQueue = [];
      set((state) => ({
        agentId: null,
        currentAgentId: null,
        isReadOnly: true,
        editedAgent: null,
        savedAgent: null,
        serverSnapshotRevision: state.serverSnapshotRevision + 1,
        isGenerating: false,
        saveError: null,
        lastSaveFailed: false,
      }));
    },
  };
});
