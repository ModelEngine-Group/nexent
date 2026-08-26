"use client";

import { useEffect, useId, useReducer, useState, type FC } from "react";
import { useAui, useAuiState } from "@assistant-ui/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Link2,
  Loader2,
  Settings2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import ToolConfigModal from "../../agents/components/agentConfig/tool/ToolConfigModal";
import SkillConfigModal from "../../agents/components/agentConfig/skill/SkillConfigModal";
import {
  findCanonicalTool,
  mergeCanonicalTool,
} from "../../agents/components/agentConfig/tool/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import { useToolList } from "@/hooks/agent/useToolList";
import { useKnowledgeBasesForToolConfig } from "@/hooks/useKnowledgeBaseSelector";
import {
  searchAgentInfo,
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
import { Nl2AgentResourceSourceBadge } from "./nl2agent-resource-source-badge";

type ConfigStatus = "unconfigured" | "valid" | "invalid";
type BindingStatus = "idle" | "binding" | "bound" | "failed";
const KNOWLEDGE_BASE_SEARCH_TOOL_NAME = "knowledge_base_search";

interface BindingItemState {
  resource: Nl2aRecommendedResource;
  selected: boolean;
  configStatus: ConfigStatus;
  bindingStatus: BindingStatus;
  draftParams: Nl2AgentResourceParam[];
  fieldErrors: Nl2AgentConfigFieldError[];
  error?: ApiError;
}

type BindingAction =
  | { type: "toggle"; ref: string }
  | { type: "save_config"; ref: string; params: Nl2AgentResourceParam[] }
  | {
      type: "hydrate_tool_configs";
      configs: Map<
        string,
        { params: Nl2AgentResourceParam[]; requiresConfirmation: boolean }
      >;
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

const parseStringArray = (value: unknown): string[] => {
  if (Array.isArray(value)) {
    return value
      .map(String)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  if (typeof value !== "string" || !value.trim()) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed)
      ? parsed
          .map(String)
          .map((item) => item.trim())
          .filter(Boolean)
      : [];
  } catch {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
};

const hydrateBoundToolConfigs = (
  resources: Nl2aRecommendedResource[],
  boundTools: Tool[],
  accessibleKnowledgeBaseIds: ReadonlySet<string>
): Map<
  string,
  { params: Nl2AgentResourceParam[]; requiresConfirmation: boolean }
> => {
  const configs = new Map<
    string,
    { params: Nl2AgentResourceParam[]; requiresConfirmation: boolean }
  >();
  resources.forEach((resource) => {
    if (resource.candidate.resource_type !== "tool") return;
    const toolId = parseResourceId(resource.candidate.candidate_ref, "tool");
    const boundTool = findCanonicalTool(boundTools, toolId);
    if (!boundTool) return;

    const values = new Map(
      boundTool.initParams.map((param) => [param.name, param.value])
    );
    let requiresConfirmation = false;
    const params = resource.config.map((param) => {
      if (!values.has(param.name)) return { ...param };
      let value = values.get(param.name);
      if (
        resource.candidate.name === KNOWLEDGE_BASE_SEARCH_TOOL_NAME &&
        param.name === "index_names"
      ) {
        const savedIds = parseStringArray(value);
        const accessibleIds = savedIds.filter((id) =>
          accessibleKnowledgeBaseIds.has(id)
        );
        requiresConfirmation = accessibleIds.length !== savedIds.length;
        value = accessibleIds;
      }
      return { ...param, value };
    });
    configs.set(resource.candidate.candidate_ref, {
      params,
      requiresConfirmation,
    });
  });
  return configs;
};

const initializeItems = (
  resources: Nl2aRecommendedResource[]
): BindingItemState[] =>
  resources.map((resource) => {
    const draftParams = resource.config.map((param) => ({ ...param }));
    const errors = validateNl2AgentResourceConfig(draftParams);
    return {
      resource,
      selected: resource.recommendation === "recommended",
      configStatus:
        draftParams.length === 0
          ? "valid"
          : errors.length
            ? "unconfigured"
            : "valid",
      bindingStatus: "idle",
      draftParams,
      fieldErrors: [],
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
        configStatus: fieldErrors.length ? "invalid" : "valid",
        fieldErrors,
        error: undefined,
      };
    }
    if (action.type === "hydrate_tool_configs") {
      const hydrated = action.configs.get(ref);
      if (!hydrated) return item;
      const fieldErrors = validateNl2AgentResourceConfig(hydrated.params);
      return {
        ...item,
        draftParams: hydrated.params,
        configStatus:
          hydrated.requiresConfirmation || fieldErrors.length
            ? "unconfigured"
            : "valid",
        fieldErrors: [],
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
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [isSynchronizing, setIsSynchronizing] = useState(false);
  const hasToolResources = payload.resources.some(
    (resource) => resource.candidate.resource_type === "tool"
  );
  const hasKnowledgeBaseSearchResource = payload.resources.some(
    (resource) =>
      resource.candidate.resource_type === "tool" &&
      resource.candidate.name === KNOWLEDGE_BASE_SEARCH_TOOL_NAME
  );
  const [hasHydratedToolConfigs, setHasHydratedToolConfigs] =
    useState(!hasToolResources);
  const {
    data: agentSnapshot,
    isFetchedAfterMount: isAgentSnapshotFetched,
    isError: isAgentSnapshotError,
    refetch: refetchAgentSnapshot,
  } = useQuery({
    queryKey: ["agentInfo", payload.agent_id],
    queryFn: async () => {
      const result = await searchAgentInfo(payload.agent_id, undefined, 0);
      if (!result.success || !result.data) {
        throw new Error(result.message);
      }
      return result.data;
    },
    enabled: hasToolResources,
    staleTime: 0,
    refetchOnMount: "always",
  });
  const {
    data: accessibleKnowledgeBases = [],
    isSuccess: isKnowledgeBaseListLoaded,
    isError: isKnowledgeBaseListError,
    refetch: refetchKnowledgeBases,
  } = useKnowledgeBasesForToolConfig(
    hasKnowledgeBaseSearchResource ? KNOWLEDGE_BASE_SEARCH_TOOL_NAME : null
  );
  const [hasRefreshedKnowledgeBases, setHasRefreshedKnowledgeBases] = useState(
    !hasKnowledgeBaseSearchResource
  );
  const {
    availableTools,
    isFetching: isToolCatalogFetching,
    isError: isToolCatalogError,
  } = useToolList({ enabled: hasToolResources });
  const waitForAutosave = useAgentStore((state) => state.waitForIdle);
  const applyPersistedResourceBindings = useAgentStore(
    (state) => state.applyPersistedResourceBindings
  );
  const replaceServerSnapshot = useAgentStore(
    (state) => state.replaceServerSnapshot
  );

  useEffect(() => {
    if (!hasKnowledgeBaseSearchResource) return;
    let active = true;
    void refetchKnowledgeBases().finally(() => {
      if (active) setHasRefreshedKnowledgeBases(true);
    });
    return () => {
      active = false;
    };
  }, [hasKnowledgeBaseSearchResource, refetchKnowledgeBases]);

  useEffect(() => {
    if (
      hasHydratedToolConfigs ||
      !agentSnapshot ||
      !isAgentSnapshotFetched ||
      isAgentSnapshotError ||
      (hasKnowledgeBaseSearchResource &&
        (!hasRefreshedKnowledgeBases ||
          !isKnowledgeBaseListLoaded ||
          isKnowledgeBaseListError))
    ) {
      return;
    }
    dispatch({
      type: "hydrate_tool_configs",
      configs: hydrateBoundToolConfigs(
        payload.resources,
        agentSnapshot.tools ?? [],
        new Set(accessibleKnowledgeBases.map((kb) => String(kb.id).trim()))
      ),
    });
    setHasHydratedToolConfigs(true);
  }, [
    accessibleKnowledgeBases,
    agentSnapshot,
    hasHydratedToolConfigs,
    hasKnowledgeBaseSearchResource,
    hasRefreshedKnowledgeBases,
    isAgentSnapshotFetched,
    isAgentSnapshotError,
    isKnowledgeBaseListError,
    isKnowledgeBaseListLoaded,
    payload.resources,
  ]);

  useEffect(() => {
    registerCard(cardKey, payload.subtype);
  }, [cardKey, payload.subtype, registerCard]);

  const isConfigHydrationFailed =
    !hasHydratedToolConfigs &&
    (isAgentSnapshotError ||
      (hasKnowledgeBaseSearchResource && isKnowledgeBaseListError));
  const isConfigHydrating =
    hasToolResources && !hasHydratedToolConfigs && !isConfigHydrationFailed;
  const isLocked = disabled || isSubmitted || !isCardInteractive(cardKey);
  const isInteractionLocked =
    isLocked || isConfigHydrating || isConfigHydrationFailed;
  const selectedItems = items.filter((item) => item.selected);
  const isBinding = items.some((item) => item.bindingStatus === "binding");
  const canContinue =
    selectedItems.length === 0 ||
    selectedItems.every((item) => item.bindingStatus === "bound");
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

  const bindSelected = async () => {
    if (isInteractionLocked || isBinding || isSynchronizing) return;
    const pending = items.filter(
      (item) => item.selected && item.bindingStatus !== "bound"
    );
    const validationErrors = new Map<string, Nl2AgentConfigFieldError[]>();
    pending.forEach((item) => {
      const errors = validateNl2AgentResourceConfig(item.draftParams);
      if (item.configStatus === "unconfigured" && errors.length === 0) {
        errors.push({
          field: "index_names",
          message: "Review the available knowledge bases before binding",
        });
      }
      if (errors.length) validationErrors.set(candidateRef(item), errors);
    });
    if (validationErrors.size) {
      dispatch({ type: "validation_failed", errors: validationErrors });
      const invalidNames = pending
        .filter((item) => validationErrors.has(candidateRef(item)))
        .map((item) => item.resource.candidate.name)
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

    if (boundItems.length) {
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
      } else {
        const ordinaryBoundItems = boundItems.filter(
          (item) =>
            item.resource.candidate.name !== KNOWLEDGE_BASE_SEARCH_TOOL_NAME
        );
        if (
          ordinaryBoundItems.length === 0 &&
          boundItems.some(
            (item) =>
              item.resource.candidate.name === KNOWLEDGE_BASE_SEARCH_TOOL_NAME
          )
        ) {
          requestConfigFocus(payload.agent_id, {
            section: "knowledge_base",
          });
        } else {
          requestConfigFocus(payload.agent_id, {
            section: "tools_skills",
            capabilityTab: ordinaryBoundItems.some(
              (item) => item.resource.candidate.resource_type === "tool"
            )
              ? "tools"
              : "skills",
          });
        }
      }
    }
  };

  const continueFlow = async () => {
    if (isInteractionLocked || !canContinue || isSynchronizing) return;
    setSummaryError(null);
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

  return (
    <section className="my-4 overflow-hidden rounded-lg border bg-card shadow-sm">
      <div className="flex items-center gap-3 border-b bg-muted/30 px-4 py-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10">
          <Link2 className="size-4 text-primary" />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">
            {t("nl2agent.resourceBinding.title", "Bind installed resources")}
          </h3>
          <p className="text-xs text-muted-foreground">
            {t(
              "nl2agent.resourceBinding.description",
              "Installed resources matching the Agent requirements."
            )}
          </p>
        </div>
      </div>

      <div className="divide-y">
        {items.map((item) => {
          const ref = candidateRef(item);
          const bound = item.bindingStatus === "bound";
          const isToolResource =
            item.resource.candidate.resource_type === "tool";
          const toolId = isToolResource
            ? /^tool:(\d+)$/.exec(ref)?.[1]
            : undefined;
          const canonicalTool =
            toolId == null
              ? undefined
              : findCanonicalTool(availableTools, toolId);
          const isToolCatalogPending =
            isToolResource && !canonicalTool && isToolCatalogFetching;
          const isToolUnavailable =
            isToolResource && !canonicalTool && !isToolCatalogFetching;
          const configureTitle = isToolCatalogPending
            ? t("toolPool.loadingTools", "Loading tools...")
            : isToolResource && isToolCatalogError
              ? t(
                  "agentConfig.tools.fetchFailed",
                  "Failed to fetch tools list, please try again later"
                )
              : isToolUnavailable
                ? t("toolPool.tooltip.unavailableTool", "Tool is unavailable")
                : t("nl2agent.resourceBinding.configure", "Configure");
          return (
            <div key={ref} className="flex min-w-0 items-start gap-3 px-4 py-3">
              <input
                type="checkbox"
                checked={item.selected}
                disabled={isInteractionLocked || bound || isBinding}
                onChange={() => dispatch({ type: "toggle", ref })}
                className="mt-1 size-4 accent-primary"
                aria-label={item.resource.candidate.name}
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="break-words text-sm font-medium">
                    {item.resource.candidate.name}
                  </span>
                  <Nl2AgentResourceSourceBadge
                    source={item.resource.candidate.source}
                  />
                  <Badge variant="outline" className="rounded-md text-[10px]">
                    {item.resource.recommendation === "recommended"
                      ? t("nl2agent.resourceBinding.recommended", "Recommended")
                      : t("nl2agent.resourceBinding.optional", "Optional")}
                  </Badge>
                  {bound ? (
                    <span className="inline-flex items-center gap-1 text-xs text-emerald-600">
                      <CheckCircle2 className="size-3.5" />
                      {t("nl2agent.resourceBinding.bound", "Bound")}
                    </span>
                  ) : item.bindingStatus === "failed" ? (
                    <span className="inline-flex items-center gap-1 text-xs text-destructive">
                      <AlertTriangle className="size-3.5" />
                      {t("nl2agent.resourceBinding.failed", "Failed")}
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 break-words text-xs text-muted-foreground">
                  {item.resource.candidate.description}
                </p>
                <p className="mt-1 break-words text-xs text-muted-foreground">
                  {t("nl2agent.resourceBinding.matches", "Matches")}:{" "}
                  {item.resource.candidate.requirement_ids.join(", ")}
                </p>
                {item.fieldErrors.length ? (
                  <p className="mt-1 text-xs text-destructive">
                    {item.fieldErrors.map((error) => error.field).join(", ")}
                  </p>
                ) : item.error ? (
                  <p className="mt-1 text-xs text-destructive">
                    {item.error.message}
                  </p>
                ) : null}
              </div>
              {item.draftParams.length ? (
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  title={configureTitle}
                  disabled={
                    isInteractionLocked ||
                    bound ||
                    isBinding ||
                    isToolCatalogPending ||
                    isToolUnavailable
                  }
                  onClick={() => setConfiguringRef(ref)}
                  className={
                    item.configStatus === "invalid" ? "border-destructive" : ""
                  }
                >
                  {isToolCatalogPending ? (
                    <Loader2 className="size-4 animate-spin" />
                  ) : (
                    <Settings2 className="size-4" />
                  )}
                </Button>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="border-t px-4 py-3">
        {isConfigHydrating ? (
          <p className="mb-3 inline-flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            {t(
              "nl2agent.resourceBinding.loadingExistingConfig",
              "Loading the current resource configuration..."
            )}
          </p>
        ) : null}
        {isConfigHydrationFailed ? (
          <div className="mb-3 flex items-center justify-between gap-3">
            <p className="text-xs text-destructive" role="alert">
              {t(
                "nl2agent.resourceBinding.loadExistingConfigFailed",
                "Failed to load the current resource configuration."
              )}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                void refetchAgentSnapshot();
                if (hasKnowledgeBaseSearchResource) {
                  void refetchKnowledgeBases();
                }
              }}
            >
              {t("common.retry", "Retry")}
            </Button>
          </div>
        ) : null}
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
          {!canContinue ? (
            <Button
              disabled={isInteractionLocked || isBinding || isSynchronizing}
              onClick={bindSelected}
            >
              {isBinding ? (
                <Loader2 className="mr-2 size-4 animate-spin" />
              ) : null}
              {items.some((item) => item.bindingStatus === "failed")
                ? t("nl2agent.resourceBinding.retry", "Retry failed")
                : t("nl2agent.resourceBinding.bind", "Bind selected")}
            </Button>
          ) : null}
          <Button
            disabled={
              canRetryGeneration ||
              isLocked ||
              !canContinue ||
              isSynchronizing ||
              isConfigHydrating ||
              isConfigHydrationFailed
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

      {toolForDialog && configuringItem ? (
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
          localOnly
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
