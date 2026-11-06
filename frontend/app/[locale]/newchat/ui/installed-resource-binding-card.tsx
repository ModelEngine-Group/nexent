// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useId, useReducer, useState, type FC } from "react";
import { useAui, useAuiState } from "@assistant-ui/react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Link2, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import ToolConfigModal from "../../agents/components/capability/tool/ToolConfigModal";
import SkillConfigModal from "../../agents/components/capability/skill/SkillConfigModal";
import {
  findCanonicalTool,
  mergeCanonicalTool,
  mergeToolParamValues,
} from "../../agents/components/capability/tool/utils";
import { Button } from "@/components/ui/button";
import {
  useNl2AgentFlow,
  type Nl2AgentConfigFocusTarget,
} from "@/contexts/nl2AgentFlow";
import { useToolList } from "@/hooks/agent/useToolList";
import { isManagedKnowledgeTool } from "@/lib/managedKnowledgeTools";
import {
  searchAgentInfo,
  searchToolConfig,
  updateToolConfig,
  saveSkillInstance,
} from "@/services/agentConfigService";
import { toApiError, type ApiError } from "@/services/api";
import { useAgentStore } from "@/stores/agentStore";
import type {
  Agent,
  Skill,
  SkillParam,
  Tool,
  ToolParam,
} from "@/types/agentConfig";
import type {
  Nl2AgentCardAction,
  Nl2aInstalledResourceBindingPayload,
  Nl2aRecommendedResource,
} from "../adapter/remote-chat-model-adapter";
import {
  nl2AgentParamsToRecord,
  readApiFieldErrors,
  validateNl2AgentResourceConfig,
  type Nl2AgentConfigFieldError,
  type Nl2AgentResourceParam,
} from "./nl2agent-resource-config";
import { Nl2AgentBindingItem } from "./nl2agent-binding-item";
import {
  knowledgeToolName,
  knowledgeSelectionIds,
  mergeKnowledgeConfig,
} from "./nl2agent-knowledge-config";
import { nl2AgentCardRunConfig } from "./nl2agent-card-run-config";

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
}

type BindingAction =
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
  | {
      type: "validation_failed";
      errors: Map<string, Nl2AgentConfigFieldError[]>;
    }
  | { type: "binding_started"; refs: Set<string> }
  | { type: "binding_succeeded"; ref: string }
  | { type: "binding_failed"; ref: string; error: ApiError };

const candidateRef = (item: BindingItemState): string =>
  item.resource.candidate.candidate_ref;

const parseResourceId = (ref: string, expected: "tool" | "skill"): number => {
  const match = new RegExp(`^${expected}:(\\d+)$`).exec(ref);
  const resourceId = Number(match?.[1]);
  if (!Number.isInteger(resourceId) || resourceId <= 0) {
    throw new Error(`Invalid ${expected} candidate reference`);
  }
  return resourceId;
};

const findBindingTool = (item: BindingItemState, tools: Tool[]) =>
  findCanonicalTool(tools, parseResourceId(candidateRef(item), "tool"));

const isManagedKnowledgeBinding = (
  item: BindingItemState,
  tools: Tool[]
): boolean => {
  if (item.resource.candidate.resource_type !== "tool") return false;
  const tool = findBindingTool(item, tools);
  return tool ? isManagedKnowledgeTool(tool) : false;
};

const isVisibleBinding = (item: BindingItemState, tools: Tool[]): boolean => {
  if (item.resource.candidate.resource_type === "skill") return true;
  return findBindingTool(item, tools)?.is_user_selectable !== false;
};

const resolveBindingFocusTarget = (
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

const initializeItems = (
  resources: Nl2aRecommendedResource[]
): BindingItemState[] =>
  resources.map((resource) => {
    const draftParams = resource.config.map((param) => ({ ...param }));
    const errors = validateNl2AgentResourceConfig(draftParams);
    return {
      resource,
      selected: resource.is_bound || resource.recommendation === "recommended",
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

function reducer(
  state: BindingItemState[],
  action: BindingAction
): BindingItemState[] {
  return state.map((item) => {
    const ref = candidateRef(item);
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
        selected: isBound ? true : item.selected,
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

const toPersistedBindings = (
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

const snapshotContainsBindings = (
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

export const InstalledResourceBindingCard: FC<{
  payload: Nl2aInstalledResourceBindingPayload;
  disabled?: boolean;
}> = ({ payload, disabled = false }) => {
  const { t } = useTranslation("common");
  const aui = useAui();
  const isRunning = useAuiState((state) => state.thread.isRunning);
  const queryClient = useQueryClient();
  const reactId = useId();
  const cardKey = `installed_resource_binding:${payload.agent_id}:${reactId}`;
  const {
    agentId: sessionAgentId,
    failedPromptFields,
    phase,
    registerCard,
    submitCard,
    markResourcesBound,
    requestConfigFocus,
    isCardInteractive,
  } = useNl2AgentFlow();
  const [items, dispatch] = useReducer(
    reducer,
    payload.resources,
    initializeItems
  );
  const [configuringRef, setConfiguringRef] = useState<string | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [loadingConfigRef, setLoadingConfigRef] = useState<string | null>(null);
  const [boundExpanded, setBoundExpanded] = useState(true);
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [isSynchronizing, setIsSynchronizing] = useState(false);
  const hasToolResources = payload.resources.some(
    (resource) => resource.candidate.resource_type === "tool"
  );
  const {
    availableTools,
    isFetching: isToolCatalogFetching,
    isError: isToolCatalogError,
  } = useToolList({ enabled: hasToolResources });
  const waitForAutosave = useAgentStore((state) => state.waitForIdle);
  const currentAgentId = useAgentStore((state) => state.currentAgentId);
  const editedAgent = useAgentStore((state) => state.editedAgent);
  const applyPersistedResourceBindings = useAgentStore(
    (state) => state.applyPersistedResourceBindings
  );
  const replaceServerSnapshot = useAgentStore(
    (state) => state.replaceServerSnapshot
  );

  useEffect(() => {
    if (currentAgentId !== payload.agent_id || !editedAgent) return;
    dispatch({
      type: "sync_bound_tools",
      refs: new Set(editedAgent.tools.map((tool) => `tool:${tool.id}`)),
      tools: editedAgent.tools,
    });
  }, [currentAgentId, editedAgent, payload.agent_id]);

  useEffect(() => {
    if (!disabled) registerCard(cardKey, payload.subtype);
  }, [cardKey, disabled, payload.subtype, registerCard]);

  const isLocked = disabled || isSubmitted || !isCardInteractive(cardKey);
  const isInteractionLocked =
    isLocked || loadingConfigRef !== null || isSynchronizing;
  const selectedItems = items.filter((item) => item.selected);
  const isBinding = items.some((item) => item.bindingStatus === "binding");
  const hasValidKnowledge = (item: BindingItemState) => {
    const name = knowledgeToolName(
      item.resource.candidate,
      item.resource.candidate.resource_type === "tool"
        ? findBindingTool(item, availableTools)
        : undefined
    );
    const ids = name ? knowledgeSelectionIds(item.draftParams, name) : [];
    return (
      !name || (ids.length > 0 && (name !== "aidp_search" || ids.length <= 10))
    );
  };
  const canContinue =
    selectedItems.length === 0 ||
    selectedItems.every(
      (item) => item.bindingStatus === "bound" && hasValidKnowledge(item)
    );
  const configuringItem = items.find(
    (item) => candidateRef(item) === configuringRef
  );
  const canRetryGeneration =
    isSubmitted &&
    !isRunning &&
    phase === "generation_failed" &&
    sessionAgentId === payload.agent_id;

  const reloadAgentSnapshot = async (
    expectedBindings: BindingItemState[]
  ): Promise<boolean> => {
    setIsSynchronizing(true);
    try {
      const result = await searchAgentInfo(payload.agent_id, undefined, 0);
      if (!result.success || !result.data) return false;
      if (!snapshotContainsBindings(result.data, expectedBindings))
        return false;
      if (!replaceServerSnapshot(payload.agent_id, result.data)) return false;

      queryClient.setQueryData(["agentInfo", payload.agent_id], result.data);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["agents"] }),
        queryClient.invalidateQueries({ queryKey: ["toolInfo"] }),
        queryClient.invalidateQueries({
          queryKey: ["agentSkillInstances", payload.agent_id],
        }),
      ]);
      return true;
    } catch {
      return false;
    } finally {
      setIsSynchronizing(false);
    }
  };

  const showSynchronizationError = () => {
    setSummaryError(
      t(
        "nl2agent.resourceBinding.syncFailed",
        "Resources were saved, but the Agent view could not be refreshed. Retry to continue."
      )
    );
  };

  const openResourceConfig = async (
    item: BindingItemState,
    canonicalTool?: Tool
  ) => {
    const ref = candidateRef(item);
    if (item.resource.candidate.resource_type === "skill") {
      setConfiguringRef(ref);
      return;
    }
    if (!canonicalTool) return;
    if (
      knowledgeToolName(item.resource.candidate, canonicalTool) &&
      item.knowledgeEdited
    ) {
      setConfiguringRef(ref);
      return;
    }
    setLoadingConfigRef(ref);
    setSummaryError(null);
    try {
      const autosaveSucceeded = await waitForAutosave();
      if (!autosaveSucceeded) {
        setSummaryError(
          t(
            "nl2agent.resourceBinding.autosaveFailed",
            "Save the pending Agent changes before binding resources."
          )
        );
        return;
      }
      const result = await searchToolConfig(
        parseResourceId(ref, "tool"),
        payload.agent_id
      );
      if (!result.success || !result.data) {
        setSummaryError(
          t(
            "nl2agent.resourceBinding.loadExistingConfigFailed",
            "Failed to load the current resource configuration."
          )
        );
        return;
      }
      dispatch({
        type: "save_config",
        ref,
        params: knowledgeToolName(item.resource.candidate, canonicalTool)
          ? mergeKnowledgeConfig(
              item.draftParams,
              knowledgeToolName(item.resource.candidate, canonicalTool)!,
              result.data.params ?? {}
            )
          : mergeToolParamValues(
              item.draftParams as ToolParam[],
              result.data.params
            ),
      });
      setConfiguringRef(ref);
    } catch {
      setSummaryError(
        t(
          "nl2agent.resourceBinding.loadExistingConfigFailed",
          "Failed to load the current resource configuration."
        )
      );
    } finally {
      setLoadingConfigRef(null);
    }
  };

  const bindSelected = async () => {
    if (isInteractionLocked || isBinding || isSynchronizing) return;
    const pending = items.filter(
      (item) =>
        item.selected &&
        (item.bindingStatus !== "bound" || !hasValidKnowledge(item))
    );
    const pendingToolWithoutCatalog = pending.some(
      (item) =>
        item.resource.candidate.resource_type === "tool" &&
        !findCanonicalTool(
          availableTools,
          parseResourceId(candidateRef(item), "tool")
        )
    );
    if (pendingToolWithoutCatalog) {
      setSummaryError(
        t(
          "agentConfig.tools.fetchFailed",
          "Failed to fetch tools list, please try again later"
        )
      );
      return;
    }
    const validationErrors = new Map<string, Nl2AgentConfigFieldError[]>();
    pending.forEach((item) => {
      const errors = validateNl2AgentResourceConfig(item.draftParams);
      if (!hasValidKnowledge(item))
        errors.push({
          field: "knowledge_base",
          message: "Select at least one knowledge base",
        });
      if (errors.length) validationErrors.set(candidateRef(item), errors);
    });
    if (validationErrors.size) {
      dispatch({ type: "validation_failed", errors: validationErrors });
      const invalidNames = pending
        .filter((item) => validationErrors.has(candidateRef(item)))
        .map((item) =>
          knowledgeToolName(
            item.resource.candidate,
            item.resource.candidate.resource_type === "tool"
              ? findBindingTool(item, availableTools)
              : undefined
          )
            ? t("nl2agent.resourceBinding.typeKnowledge", "Knowledge")
            : item.resource.candidate.name
        )
        .join(", ");
      setSummaryError(
        `${t(
          "nl2agent.resourceBinding.validationSummary",
          "Complete the configuration for every selected resource."
        )} ${invalidNames}`
      );
      setConfiguringRef(validationErrors.keys().next().value ?? null);
      return;
    }
    if (!pending.length) return;

    const autosaveSucceeded = await waitForAutosave();
    if (!autosaveSucceeded) {
      setSummaryError(
        t(
          "nl2agent.resourceBinding.autosaveFailed",
          "Save the pending Agent changes before binding resources."
        )
      );
      return;
    }

    setSummaryError(null);
    dispatch({
      type: "binding_started",
      refs: new Set(pending.map(candidateRef)),
    });
    const settled = await Promise.allSettled(
      pending.map(async (item) => {
        const ref = candidateRef(item);
        const params = nl2AgentParamsToRecord(item.draftParams);
        const result =
          item.resource.candidate.resource_type === "tool"
            ? await updateToolConfig(
                parseResourceId(ref, "tool"),
                payload.agent_id,
                params,
                true
              )
            : await saveSkillInstance(
                parseResourceId(ref, "skill"),
                payload.agent_id,
                true,
                0,
                params
              );
        if (!result.success) {
          throw result.error ?? new Error(result.message);
        }
        return item;
      })
    );
    const boundItems: BindingItemState[] = [];
    settled.forEach((result, index) => {
      const ref = candidateRef(pending[index]);
      if (result.status === "fulfilled") {
        boundItems.push(result.value);
        dispatch({ type: "binding_succeeded", ref });
      } else {
        dispatch({
          type: "binding_failed",
          ref,
          error: toApiError(result.reason),
        });
      }
    });

    if (!boundItems.length) return;

    const persistedBindings = toPersistedBindings(
      boundItems,
      queryClient.getQueryData<Tool[]>(["tools"]) ?? [],
      queryClient.getQueryData<Skill[]>(["skills"]) ?? []
    );
    const applied = applyPersistedResourceBindings(
      payload.agent_id,
      persistedBindings
    );
    const synchronized =
      applied &&
      (await reloadAgentSnapshot([
        ...items.filter((item) => item.bindingStatus === "bound"),
        ...boundItems,
      ]));
    if (!synchronized) {
      showSynchronizationError();
      return;
    }

    const focusTarget = resolveBindingFocusTarget(boundItems, availableTools);
    if (focusTarget) requestConfigFocus(payload.agent_id, focusTarget);
  };

  const continueFlow = async () => {
    if (isInteractionLocked || !canContinue || isSynchronizing) return;
    setSummaryError(null);
    const autosaveSucceeded = await waitForAutosave();
    if (!autosaveSucceeded) {
      setSummaryError(
        t(
          "nl2agent.resourceBinding.autosaveFailed",
          "Save the pending Agent changes before binding resources."
        )
      );
      return;
    }
    const synchronized = await reloadAgentSnapshot(
      items.filter((item) => item.bindingStatus === "bound")
    );
    if (!synchronized) {
      showSynchronizationError();
      return;
    }

    const action: Nl2AgentCardAction = {
      type: "nl2agent_card_action",
      subtype: payload.subtype,
      agent_id: payload.agent_id,
      action: "continue",
      result: {
        bound: items
          .filter((item) => item.bindingStatus === "bound")
          .map((item) => ({
            resource_type: item.resource.candidate.resource_type,
            resource_id: parseResourceId(
              candidateRef(item),
              item.resource.candidate.resource_type
            ),
          })),
        skipped_candidate_refs: items
          .filter((item) => !item.selected)
          .map(candidateRef),
      },
    };
    setIsSubmitted(true);
    submitCard(cardKey);
    markResourcesBound(payload.agent_id);
    aui.thread().append({
      runConfig: nl2AgentCardRunConfig(
        aui.thread().composer().getState().runConfig,
        payload.agent_id
      ),
      role: "user",
      content: [
        {
          type: "text",
          text: t(
            "nl2agent.resourceBinding.submittedSummary",
            "Resource selection completed"
          ),
        },
      ],
      metadata: { custom: { nl2agentCardAction: action } },
      startRun: true,
    });
  };

  const retryGeneration = () => {
    if (!canRetryGeneration || disabled) return;
    markResourcesBound(payload.agent_id);
    const action: Nl2AgentCardAction = {
      type: "nl2agent_card_action",
      subtype: payload.subtype,
      agent_id: payload.agent_id,
      action: "retry_generation",
      result: { failed_fields: failedPromptFields },
    };
    aui.thread().append({
      runConfig: nl2AgentCardRunConfig(
        aui.thread().composer().getState().runConfig,
        payload.agent_id
      ),
      role: "user",
      content: [
        {
          type: "text",
          text: t(
            "nl2agent.resourceBinding.retryGenerationSummary",
            "Retrying Prompt generation"
          ),
        },
      ],
      metadata: { custom: { nl2agentCardAction: action } },
      startRun: true,
    });
  };

  const dialogResource = configuringItem?.resource;
  const dialogToolId =
    dialogResource?.candidate.resource_type === "tool"
      ? parseResourceId(dialogResource.candidate.candidate_ref, "tool")
      : null;
  const dialogCanonicalTool =
    dialogToolId == null
      ? undefined
      : findCanonicalTool(availableTools, dialogToolId);
  const toolForDialog: Tool | null =
    dialogResource?.candidate.resource_type === "tool" &&
    dialogToolId != null &&
    dialogCanonicalTool
      ? mergeCanonicalTool(
          {
            id: String(dialogToolId),
            name: dialogResource.candidate.name,
            description: dialogResource.candidate.description,
            source:
              dialogResource.candidate.source === "LOCAL_TOOL"
                ? "local"
                : "mcp",
            initParams: (configuringItem?.draftParams ?? []) as ToolParam[],
          },
          availableTools
        )
      : null;
  const skillForDialog: Skill | null =
    dialogResource?.candidate.resource_type === "skill"
      ? {
          skill_id: parseResourceId(
            dialogResource.candidate.candidate_ref,
            "skill"
          ),
          name: dialogResource.candidate.name,
          description: dialogResource.candidate.description,
          source: dialogResource.candidate.source,
          config_schemas: (configuringItem?.draftParams ?? []) as SkillParam[],
        }
      : null;

  const pendingItems = items.filter((item) => item.bindingStatus !== "bound");
  const boundItems = items.filter((item) => item.bindingStatus === "bound");
  const pendingSelected = pendingItems.filter((item) => item.selected);
  const renderResource = (item: BindingItemState) => {
    const ref = candidateRef(item);
    const tool =
      item.resource.candidate.resource_type === "tool"
        ? findCanonicalTool(availableTools, parseResourceId(ref, "tool"))
        : undefined;
    return (
      <Nl2AgentBindingItem
        key={ref}
        item={item}
        tool={tool}
        ui={{
          locked: isInteractionLocked,
          binding: isBinding,
          catalogFetching: isToolCatalogFetching,
          catalogError: isToolCatalogError,
          configLoading: loadingConfigRef === ref,
          configuring: configuringRef === ref,
        }}
        onToggle={() => dispatch({ type: "toggle", ref })}
        onConfigure={() => void openResourceConfig(item, tool)}
        onCloseConfig={() => setConfiguringRef(null)}
        onSaveKnowledge={(params) =>
          dispatch({ type: "save_config", ref, params, knowledgeEdited: true })
        }
      />
    );
  };

  return (
    <section className="my-4 overflow-hidden rounded-2xl border border-border bg-white text-foreground shadow-sm dark:bg-card">
      <div className="flex items-center gap-3 border-b px-4 py-3.5">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
          <Link2 className="size-4" />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">
            {t("nl2agent.resourceBinding.title", "Bind installed resources")}
          </h3>
          <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
            {t(
              "nl2agent.resourceBinding.description",
              "Select and configure matching resources, then bind them together."
            )}
          </p>
        </div>
      </div>
      <div
        role="region"
        aria-label={t(
          "nl2agent.resourceBinding.pendingResources",
          "Resources to bind"
        )}
      >
        <div className="flex items-center justify-between gap-2 px-4 py-2.5 text-xs text-muted-foreground">
          <span>
            {t(
              "nl2agent.resourceBinding.pendingResources",
              "Resources to bind"
            )}{" "}
            <span className="ml-1 tabular-nums">{pendingItems.length}</span>
          </span>
          <span aria-live="polite">
            {t("nl2agent.resourceBinding.selectedCountLabel", "Selected")}{" "}
            <span className="tabular-nums">{pendingSelected.length}</span>{" "}
            {t("nl2agent.resourceBinding.itemsUnit", "items")}
          </span>
        </div>
        <div className="divide-y">{pendingItems.map(renderResource)}</div>
        {!pendingItems.length ? (
          <p className="px-4 pb-3 text-xs text-muted-foreground">
            {t(
              "nl2agent.resourceBinding.noPending",
              "No resources awaiting binding."
            )}
          </p>
        ) : null}
      </div>
      {boundItems.length ? (
        <div
          role="region"
          aria-label={t(
            "nl2agent.resourceBinding.boundResources",
            "Bound resources"
          )}
          className="border-t bg-muted/20"
        >
          <button
            type="button"
            aria-expanded={boundExpanded}
            aria-controls={`${cardKey}:bound`}
            disabled={isInteractionLocked || isBinding}
            onClick={() => setBoundExpanded((expanded) => !expanded)}
            className="flex w-full items-center justify-between gap-2 px-4 py-2.5 text-xs text-muted-foreground hover:bg-muted/40"
          >
            <span className="inline-flex items-center gap-2">
              {t("nl2agent.resourceBinding.boundResources", "Bound resources")}
              <span className="inline-flex min-w-5 items-center justify-center rounded-full border bg-background px-1 text-[10px] tabular-nums">
                {boundItems.length}
              </span>
            </span>
            <span className="inline-flex items-center gap-1">
              {boundExpanded
                ? t("nl2agent.resourceBinding.collapse", "Collapse")
                : t("nl2agent.resourceBinding.expand", "Expand")}
              {boundExpanded ? (
                <ChevronUp className="size-3" />
              ) : (
                <ChevronDown className="size-3" />
              )}
            </span>
          </button>
          {boundExpanded ? (
            <div id={`${cardKey}:bound`} className="divide-y px-0">
              {boundItems.map(renderResource)}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="border-t px-4 py-3">
        {summaryError ? (
          <p className="mb-3 text-xs text-destructive" role="alert">
            {summaryError}
          </p>
        ) : null}
        <div className="flex flex-wrap justify-end gap-2">
          {canRetryGeneration ? (
            <Button disabled={disabled} onClick={retryGeneration}>
              {t(
                "nl2agent.resourceBinding.retryGeneration",
                "Retry Prompt generation"
              )}
            </Button>
          ) : null}
          <Button
            disabled={
              isInteractionLocked ||
              isBinding ||
              isSynchronizing ||
              pendingSelected.length === 0
            }
            onClick={bindSelected}
          >
            {isBinding ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : null}
            {items.some((item) => item.bindingStatus === "failed") ? (
              t("nl2agent.resourceBinding.retry", "Retry failed")
            ) : (
              <>
                {t("nl2agent.resourceBinding.bind", "Bind selected")} (
                {pendingSelected.length})
              </>
            )}
          </Button>
          <Button
            className="disabled:bg-muted disabled:text-muted-foreground disabled:opacity-100"
            disabled={
              canRetryGeneration ||
              isLocked ||
              !canContinue ||
              isSynchronizing ||
              loadingConfigRef !== null
            }
            onClick={continueFlow}
          >
            {isSynchronizing ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : null}
            {selectedItems.length === 0
              ? t("nl2agent.resourceBinding.skip", "Skip")
              : t("nl2agent.resourceBinding.continue", "Continue")}
          </Button>
        </div>
      </div>

      {toolForDialog &&
      configuringItem &&
      !knowledgeToolName(
        configuringItem.resource.candidate,
        dialogCanonicalTool
      ) ? (
        <ToolConfigModal
          isOpen
          onCancel={() => setConfiguringRef(null)}
          onSave={(params: ToolParam[]) =>
            dispatch({
              type: "save_config",
              ref: candidateRef(configuringItem),
              params,
            })
          }
          tool={toolForDialog}
          initialParams={configuringItem.draftParams as ToolParam[]}
          selectedTool={toolForDialog}
          currentAgentId={payload.agent_id}
          localOnly={configuringItem.bindingStatus !== "bound"}
        />
      ) : null}
      {skillForDialog && configuringItem ? (
        <SkillConfigModal
          isOpen
          onCancel={() => setConfiguringRef(null)}
          onSave={(params: SkillParam[]) =>
            dispatch({
              type: "save_config",
              ref: candidateRef(configuringItem),
              params,
            })
          }
          skill={skillForDialog}
          initialParams={configuringItem.draftParams as SkillParam[]}
          currentAgentId={payload.agent_id}
        />
      ) : null}
    </section>
  );
};
