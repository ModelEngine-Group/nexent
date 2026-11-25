// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { findCanonicalTool } from "../../agents/components/capability/tool/utils";
import { isManagedKnowledgeTool } from "@/lib/managedKnowledgeTools";
import type {
  Agent,
  Tool,
  Skill,
  ToolParam,
  SkillParam,
} from "@/types/agentConfig";
import type { ApiError } from "@/services/api";
import type { Nl2AgentConfigFocusTarget } from "@/contexts/nl2AgentFlow";
import type { Nl2aRecommendedResource } from "../adapter/remote-chat-model-adapter";
import type { Nl2AgentKnowledgePreparation } from "@/types/nl2AgentKnowledge";
import {
  nl2AgentParamsToRecord,
  readApiFieldErrors,
  validateNl2AgentResourceConfig,
  type Nl2AgentConfigFieldError,
  type Nl2AgentResourceParam,
} from "./nl2agent-resource-config";
import {
  knowledgeToolName,
  knowledgeSelectionIds,
  mergeKnowledgeConfig,
} from "./nl2agent-knowledge-config";

type ConfigStatus = "unconfigured" | "valid" | "invalid";
type BindingStatus = "idle" | "binding" | "bound" | "failed";

export interface BindingItemState {
  resource: Nl2aRecommendedResource;
  selected: boolean;
  configStatus: ConfigStatus;
  bindingStatus: BindingStatus;
  draftParams: Nl2AgentResourceParam[];
  fieldErrors: Nl2AgentConfigFieldError[];
  error?: ApiError;
  knowledgeEdited?: boolean;
  knowledgePreparation?: Nl2AgentKnowledgePreparation;
}

type BindingAction =
  | {
      type: "knowledge_prepared";
      ref: string;
      prepared: Nl2AgentKnowledgePreparation;
      params: Nl2AgentResourceParam[];
    }
  | { type: "set_selected"; refs: Set<string> }
  | { type: "toggle"; ref: string }
  | {
      type: "save_config";
      ref: string;
      params: Nl2AgentResourceParam[];
      knowledgeEdited?: boolean;
    }
  | {
      type: "sync_bound_tools";
      refs: Set<string>;
      tools: Tool[];
    }
  | { type: "sync_bound_skills"; skills: Skill[] }
  | {
      type: "validation_failed";
      errors: Map<string, Nl2AgentConfigFieldError[]>;
    }
  | { type: "binding_started"; refs: Set<string> }
  | { type: "binding_succeeded"; ref: string }
  | { type: "binding_failed"; ref: string; error: ApiError };

export const candidateRef = (item: BindingItemState): string =>
  item.resource.candidate.candidate_ref;

export const parseResourceId = (
  ref: string,
  expected: "tool" | "skill"
): number => {
  const match = new RegExp(`^${expected}:(\\d+)$`).exec(ref);
  const resourceId = Number(match?.[1]);
  if (!Number.isInteger(resourceId) || resourceId <= 0) {
    throw new Error(`Invalid ${expected} candidate reference`);
  }
  return resourceId;
};

export const findBindingTool = (item: BindingItemState, tools: Tool[]) =>
  findCanonicalTool(tools, parseResourceId(candidateRef(item), "tool"));

export const isManagedKnowledgeBinding = (
  item: BindingItemState,
  tools: Tool[]
): boolean => {
  if (item.resource.candidate.resource_type !== "tool") return false;
  const tool = findBindingTool(item, tools);
  return tool ? isManagedKnowledgeTool(tool) : false;
};

export const isVisibleBinding = (
  item: BindingItemState,
  tools: Tool[]
): boolean => {
  if (item.resource.candidate.resource_type === "skill") return true;
  return findBindingTool(item, tools)?.is_user_selectable !== false;
};

export const resolveBindingFocusTarget = (
  boundItems: BindingItemState[],
  tools: Tool[]
): Nl2AgentConfigFocusTarget | null => {
  if (boundItems.every((item) => isManagedKnowledgeBinding(item, tools))) {
    return { section: "knowledge_base" };
  }

  const visibleBoundItems = boundItems.filter((item) =>
    isVisibleBinding(item, tools)
  );
  if (!visibleBoundItems.length) return null;
  return {
    section: "tools_skills",
    capabilityTab: visibleBoundItems.some(
      (item) => item.resource.candidate.resource_type === "tool"
    )
      ? "tools"
      : "skills",
  };
};

export const initializeItems = (
  resources: Nl2aRecommendedResource[]
): BindingItemState[] =>
  resources.map((resource) => {
    const draftParams = resource.config.map((param) => ({ ...param }));
    const errors = validateNl2AgentResourceConfig(draftParams);
    return {
      resource,
      selected: resource.is_bound
        ? resource.readiness !== "not_ready"
        : resource.recommendation === "recommended",
      configStatus:
        draftParams.length === 0
          ? "valid"
          : errors.length
            ? "unconfigured"
            : "valid",
      bindingStatus: resource.is_bound ? "bound" : "idle",
      draftParams,
      fieldErrors: [],
      knowledgeEdited: Boolean(resource.knowledge_recommendations?.length),
    };
  });

export function reducer(
  state: BindingItemState[],
  action: BindingAction
): BindingItemState[] {
  if (
    action.type === "knowledge_prepared" &&
    state.find((item) => candidateRef(item) === action.ref)
      ?.knowledgePreparation === action.prepared
  )
    return state;
  return state.map((item) => {
    const ref = candidateRef(item);
    if (
      action.type === "sync_bound_skills" &&
      item.resource.candidate.resource_type === "skill" &&
      item.bindingStatus !== "binding"
    ) {
      const skill = action.skills.find(
        (entry) => Number(entry.skill_id) === parseResourceId(ref, "skill")
      );
      if (!skill) {
        if (item.bindingStatus !== "bound") return item;
        return {
          ...item,
          bindingStatus: "idle",
          resource: { ...item.resource, is_bound: false, readiness: "unbound" },
        };
      }
      const values = skill.config_values ?? {};
      const draftParams = (skill.config_schemas ?? item.resource.config).map(
        (param) => ({
          ...param,
          value: Object.prototype.hasOwnProperty.call(values, param.name)
            ? values[param.name]
            : param.value,
        })
      );
      const fieldErrors = validateNl2AgentResourceConfig(draftParams);
      return {
        ...item,
        bindingStatus: "bound",
        selected: fieldErrors.length === 0,
        resource: {
          ...item.resource,
          is_bound: true,
          readiness: fieldErrors.length ? "not_ready" : "ready",
        },
        draftParams,
        fieldErrors,
        configStatus: fieldErrors.length ? "invalid" : "valid",
        error: undefined,
      };
    }
    if (action.type === "knowledge_prepared" && ref === action.ref) {
      if (item.knowledgePreparation === action.prepared) return item;
      if (item.knowledgeEdited)
        return { ...item, knowledgePreparation: action.prepared };
      const field =
        action.prepared.tool_name === "aidp_search"
          ? "kds_list"
          : "index_names";
      const params = mergeKnowledgeConfig(
        action.params,
        action.prepared.tool_name,
        {
          ...action.prepared.settings,
          [field]:
            action.prepared.tool_name === "aidp_search"
              ? JSON.stringify(action.prepared.selected_values)
              : action.prepared.selected_values,
        }
      );
      const fieldErrors = validateNl2AgentResourceConfig(params);
      return {
        ...item,
        knowledgePreparation: action.prepared,
        draftParams: params,
        fieldErrors,
        configStatus: fieldErrors.length ? "unconfigured" : "valid",
      };
    }
    if (action.type === "set_selected")
      return {
        ...item,
        selected:
          (item.bindingStatus === "bound" &&
            item.resource.readiness !== "not_ready") ||
          action.refs.has(ref),
      };
    if (
      action.type === "toggle" &&
      ref === action.ref &&
      item.bindingStatus !== "bound"
    ) {
      return { ...item, selected: !item.selected };
    }
    if (action.type === "save_config" && ref === action.ref) {
      const fieldErrors = validateNl2AgentResourceConfig(action.params);
      return {
        ...item,
        draftParams: action.params,
        ...(action.knowledgeEdited
          ? { knowledgeEdited: true, bindingStatus: "idle" as const }
          : {}),
        configStatus: fieldErrors.length ? "invalid" : "valid",
        fieldErrors,
        error: undefined,
      };
    }
    if (
      action.type === "sync_bound_tools" &&
      item.resource.candidate.resource_type === "tool" &&
      item.bindingStatus !== "binding"
    ) {
      if (item.knowledgeEdited) return item;
      const isBound = action.refs.has(ref);
      const tool = findBindingTool(item, action.tools);
      const managed = knowledgeToolName(item.resource.candidate, tool);
      const hasSelection =
        !managed ||
        knowledgeSelectionIds(tool?.initParams ?? [], managed).length > 0;
      return {
        ...item,
        selected:
          isBound && item.resource.readiness !== "not_ready"
            ? true
            : item.selected,
        bindingStatus: isBound && hasSelection ? "bound" : "idle",
        ...(managed && tool
          ? {
              draftParams: mergeKnowledgeConfig(
                item.draftParams,
                managed,
                nl2AgentParamsToRecord(tool.initParams ?? [])
              ),
            }
          : {}),
        error: undefined,
      };
    }
    if (action.type === "validation_failed") {
      const fieldErrors = action.errors.get(ref);
      return fieldErrors
        ? { ...item, configStatus: "invalid", fieldErrors }
        : item;
    }
    if (action.type === "binding_started" && action.refs.has(ref)) {
      return { ...item, bindingStatus: "binding", error: undefined };
    }
    if (action.type === "binding_succeeded" && ref === action.ref) {
      return {
        ...item,
        selected: true,
        configStatus: "valid",
        bindingStatus: "bound",
        knowledgeEdited: false,
        fieldErrors: [],
        error: undefined,
      };
    }
    if (action.type === "binding_failed" && ref === action.ref) {
      return {
        ...item,
        bindingStatus: "failed",
        fieldErrors: readApiFieldErrors(action.error.details),
        error: action.error,
      };
    }
    return item;
  });
}

export const toPersistedBindings = (
  boundItems: BindingItemState[],
  toolCatalog: Tool[],
  skillCatalog: Skill[]
): { tools?: Tool[]; skills?: Skill[] } => {
  const tools = boundItems
    .filter((item) => item.resource.candidate.resource_type === "tool")
    .map((item) => {
      const toolId = parseResourceId(candidateRef(item), "tool");
      const canonical = findCanonicalTool(toolCatalog, toolId);
      return {
        ...canonical,
        id: String(toolId),
        name: canonical?.name || item.resource.candidate.name,
        description:
          canonical?.description || item.resource.candidate.description,
        source:
          canonical?.source ||
          (item.resource.candidate.source === "LOCAL_TOOL" ? "local" : "mcp"),
        initParams: item.draftParams as ToolParam[],
        is_available: true,
      } satisfies Tool;
    });
  const skills = boundItems
    .filter((item) => item.resource.candidate.resource_type === "skill")
    .map((item) => {
      const skillId = parseResourceId(candidateRef(item), "skill");
      const canonical = skillCatalog.find(
        (skill) => Number(skill.skill_id) === skillId
      );
      return {
        ...canonical,
        skill_id: skillId,
        name: canonical?.name || item.resource.candidate.name,
        description:
          canonical?.description || item.resource.candidate.description,
        source: canonical?.source || "custom",
        config_schemas:
          canonical?.config_schemas || (item.draftParams as SkillParam[]),
        config_values: nl2AgentParamsToRecord(item.draftParams),
      } satisfies Skill;
    });

  return {
    ...(tools.length ? { tools } : {}),
    ...(skills.length ? { skills } : {}),
  };
};

export const snapshotContainsBindings = (
  agent: Agent,
  boundItems: BindingItemState[]
): boolean => {
  const toolIds = new Set((agent.tools ?? []).map((tool) => Number(tool.id)));
  const skillIds = new Set(
    (agent.skills ?? []).map((skill) => Number(skill.skill_id))
  );
  return boundItems.every((item) => {
    const resourceType = item.resource.candidate.resource_type;
    const resourceId = parseResourceId(candidateRef(item), resourceType);
    return resourceType === "tool"
      ? toolIds.has(resourceId)
      : skillIds.has(resourceId);
  });
};
