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
import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import { useToolList } from "@/hooks/agent/useToolList";
import {
  fetchSkillById,
  fetchSkillInstances,
  searchAgentInfo,
  searchToolConfig,
  updateToolConfig,
  saveSkillInstance,
} from "@/services/agentConfigService";
import { toApiError } from "@/services/api";
import { useAgentStore } from "@/stores/agentStore";
import type { Skill, SkillParam, Tool, ToolParam } from "@/types/agentConfig";
import type {
  Nl2AgentCardAction,
  Nl2aInstalledResourceBindingPayload,
  Nl2aUnifiedResourcesPayload,
} from "../adapter/remote-chat-model-adapter";
import {
  nl2AgentParamsToRecord,
  validateNl2AgentResourceConfig,
  type Nl2AgentConfigFieldError,
} from "./nl2agent-resource-config";
import { Nl2AgentBindingItem } from "./nl2agent-binding-item";
import {
  knowledgeToolName,
  knowledgeSelectionIds,
  mergeKnowledgeConfig,
} from "./nl2agent-knowledge-config";
import { formatNl2AgentActionSummary } from "./nl2agent-action-summary";
import { nl2AgentCardRunConfig } from "./nl2agent-card-run-config";
import { RequirementCoverageCard } from "./requirement-coverage-card";
import { useNl2AgentKnowledgeRecommendations } from "./use-nl2agent-knowledge-recommendations";
import {
  restoreUnifiedDraft,
  type UnifiedResourceDraft,
} from "./nl2agent-unified-draft";

import {
  candidateRef,
  parseResourceId,
  findBindingTool,
  resolveBindingFocusTarget,
  initializeItems,
  reducer,
  toPersistedBindings,
  snapshotContainsBindings,
  type BindingItemState,
} from "./nl2agent-binding-state";
export type { BindingItemState } from "./nl2agent-binding-state";

export const InstalledResourceBindingCard: FC<{
  payload: Nl2aInstalledResourceBindingPayload | Nl2aUnifiedResourcesPayload;
  disabled?: boolean;
  unifiedPayload?: Nl2aUnifiedResourcesPayload;
}> = ({ payload, disabled = false, unifiedPayload }) => {
  const { t } = useTranslation("common");
  const aui = useAui();
  const isRunning = useAuiState((state) => state.thread.isRunning);
  const queryClient = useQueryClient();
  const reactId = useId();
  const cardKey =
    payload.card_id ??
    `installed_resource_binding:${payload.agent_id}:${reactId}`;
  const versioned = payload.protocol_version === 2;
  const {
    agentId: sessionAgentId,
    failedPromptFields,
    phase,
    registerCard,
    submitCard,
    markResourcesBound,
    requestConfigFocus,
    isCardInteractive,
    sessionGeneration,
    resourceDrafts,
  } = useNl2AgentFlow();
  const draftKey = `${sessionGeneration}:${payload.agent_id}:${unifiedPayload?.conversation_id ?? ""}`;
  const [initialDraft] = useState(() => {
    const previous = unifiedPayload?.previous_card_id
      ? (resourceDrafts.get(
          `${draftKey}:${unifiedPayload.previous_card_id}`
        ) as UnifiedResourceDraft | undefined)
      : undefined;
    return unifiedPayload
      ? restoreUnifiedDraft(
          unifiedPayload,
          initializeItems(payload.resources),
          previous
        )
      : undefined;
  });
  const [items, dispatch] = useReducer(
    reducer,
    initialDraft?.items ?? initializeItems(payload.resources)
  );
  const [selections, setSelections] = useState<Record<string, string[]>>(
    initialDraft?.selections ?? {}
  );
  const preserveDraft = () => {
    if (!unifiedPayload) return;
    resourceDrafts.set(`${draftKey}:${payload.card_id}`, {
      queries: Object.fromEntries(
        unifiedPayload.requirements.map((row) => [
          row.requirement_id,
          row.query,
        ])
      ),
      selections,
      items,
    });
  };
  const [requirementEditing, setRequirementEditing] = useState(false);
  const [resourceOperationBusy, setResourceOperationBusy] = useState(false);
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
  const savedAgent = useAgentStore((state) => state.savedAgent);
  const applyPersistedResourceBindings = useAgentStore(
    (state) => state.applyPersistedResourceBindings
  );
  const replaceServerSnapshot = useAgentStore(
    (state) => state.replaceServerSnapshot
  );
  const hasKnowledgeTools = payload.resources.some((resource) =>
    knowledgeToolName(
      resource.candidate,
      resource.candidate.resource_type === "tool"
        ? findCanonicalTool(
            availableTools,
            parseResourceId(resource.candidate.candidate_ref, "tool")
          )
        : undefined
    )
  );
  const knowledgeQuery = useNl2AgentKnowledgeRecommendations(
    unifiedPayload,
    !disabled &&
      !isSubmitted &&
      !isRunning &&
      hasKnowledgeTools &&
      isCardInteractive(cardKey),
    draftKey
  );
  useEffect(() => {
    if (configuringRef !== null) return;
    for (const prepared of knowledgeQuery.data ?? []) {
      const tool = findCanonicalTool(
        availableTools,
        parseResourceId(prepared.candidate_ref, "tool")
      );
      if (tool)
        dispatch({
          type: "knowledge_prepared",
          ref: prepared.candidate_ref,
          prepared,
          params: tool.initParams ?? [],
        });
    }
  }, [knowledgeQuery.data, availableTools, configuringRef]);

  useEffect(() => {
    if (currentAgentId !== payload.agent_id || !editedAgent) return;
    dispatch({
      type: "sync_bound_tools",
      refs: new Set(editedAgent.tools.map((tool) => `tool:${tool.id}`)),
      tools: editedAgent.tools,
    });
  }, [currentAgentId, editedAgent, payload.agent_id]);

  const canSyncSavedBindings =
    !disabled && !isSubmitted && isCardInteractive(cardKey);
  useEffect(() => {
    if (
      !canSyncSavedBindings ||
      currentAgentId !== payload.agent_id ||
      !savedAgent ||
      !Array.isArray(savedAgent.skills)
    )
      return;
    dispatch({ type: "sync_bound_skills", skills: savedAgent.skills });
  }, [canSyncSavedBindings, currentAgentId, savedAgent, payload.agent_id]);

  useEffect(() => {
    if (!disabled) registerCard(cardKey, payload.subtype, versioned);
  }, [
    cardKey,
    disabled,
    payload.subtype,
    registerCard,
    versioned,
    sessionGeneration,
  ]);

  const isLocked = disabled || isSubmitted || !isCardInteractive(cardKey);
  const areResourceOperationsLocked =
    isLocked ||
    resourceOperationBusy ||
    isRunning ||
    loadingConfigRef !== null ||
    isSynchronizing ||
    requirementEditing;
  const isInteractionLocked =
    areResourceOperationsLocked || configuringRef !== null;
  const selectedItems = items.filter((item) => item.selected);
  const isBinding = items.some((item) => item.bindingStatus === "binding");
  const hasValidKnowledge = (item: BindingItemState) => {
    if (
      item.bindingStatus === "bound" &&
      item.resource.readiness === "not_ready"
    )
      return false;
    if (
      item.bindingStatus === "bound" &&
      item.resource.readiness === "ready" &&
      !item.knowledgeEdited
    )
      return true;
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
    (!versioned ||
      (payload.requirements ?? []).every(
        (row) =>
          !row.required ||
          items.some(
            (item) =>
              item.bindingStatus === "bound" &&
              hasValidKnowledge(item) &&
              row.covered_resources.some(
                (resource) => resource.candidate_ref === candidateRef(item)
              )
          )
      )) &&
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
    if (item.resource.candidate.resource_type === "skill" && !versioned) {
      setConfiguringRef(ref);
      return;
    }
    if (item.resource.candidate.resource_type === "tool" && !canonicalTool)
      return;
    if (
      canonicalTool &&
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
      if (item.resource.candidate.resource_type === "skill") {
        const id = parseResourceId(ref, "skill");
        const [detail, instances] = await Promise.all([
          fetchSkillById(id),
          fetchSkillInstances(payload.agent_id),
        ]);
        if (!detail.success || !instances.success)
          throw new Error("Skill configuration unavailable");
        const config: SkillParam[] = detail.data?.config_schemas ?? [];
        const saved = instances.data.find(
          (instance: { skill_id: string }) => Number(instance.skill_id) === id
        )?.config_values;
        dispatch({
          type: "save_config",
          ref,
          params: config.map((param) => ({
            ...param,
            value: saved?.[param.name] ?? param.value,
          })),
        });
        setConfiguringRef(ref);
        return;
      }
      if (!canonicalTool) return;
      const result = await searchToolConfig(
        parseResourceId(ref, "tool"),
        payload.agent_id
      );
      if ((!result.success || !result.data) && item.bindingStatus === "bound") {
        setSummaryError(
          t(
            "nl2agent.resourceBinding.loadExistingConfigFailed",
            "Failed to load the current resource configuration."
          )
        );
        return;
      }
      const baseParams =
        versioned && !item.draftParams.length
          ? (canonicalTool.initParams ?? [])
          : item.draftParams;
      const savedValues = { ...result.data?.params };
      const knowledgeName = knowledgeToolName(
        item.resource.candidate,
        canonicalTool
      );
      if (knowledgeName && item.knowledgePreparation) {
        const range =
          knowledgeName === "aidp_search" ? "kds_list" : "index_names";
        if (!(range in savedValues))
          savedValues[range] =
            knowledgeName === "aidp_search"
              ? JSON.stringify(
                  knowledgeSelectionIds(item.draftParams, knowledgeName)
                )
              : knowledgeSelectionIds(item.draftParams, knowledgeName);
      }
      dispatch({
        type: "save_config",
        ref,
        params: knowledgeToolName(item.resource.candidate, canonicalTool)
          ? mergeKnowledgeConfig(
              baseParams,
              knowledgeToolName(item.resource.candidate, canonicalTool)!,
              savedValues
            )
          : mergeToolParamValues(
              baseParams as ToolParam[],
              result.data?.params
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
    if (
      knowledgeQuery.isFetching &&
      selectedItems.some(
        (item) =>
          !item.knowledgeEdited &&
          knowledgeToolName(
            item.resource.candidate,
            item.resource.candidate.resource_type === "tool"
              ? findBindingTool(item, availableTools)
              : undefined
          )
      )
    )
      return;
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
      if (item.resource.has_config && !item.draftParams.length)
        errors.push({
          field: "config",
          message: t(
            "nl2agent.coverage.configureFirst",
            "Open configuration before binding."
          ),
        });
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
      const firstInvalidItem = pending.find((item) =>
        validationErrors.has(candidateRef(item))
      );
      if (firstInvalidItem) {
        await openResourceConfig(
          firstInvalidItem,
          firstInvalidItem.resource.candidate.resource_type === "tool"
            ? findBindingTool(firstInvalidItem, availableTools)
            : undefined
        );
      }
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
      ...(payload.card_id ? { card_id: payload.card_id } : {}),
      subtype: payload.subtype,
      agent_id: payload.agent_id,
      action: "continue",
      result: versioned
        ? {
            card_id: payload.card_id,
            state_version: payload.state_version,
            selected_resource_refs: selectedItems.map(candidateRef),
          }
        : {
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
    if (!versioned) {
      setIsSubmitted(true);
      submitCard(cardKey);
      markResourcesBound(payload.agent_id);
    }
    aui.thread().append({
      runConfig: nl2AgentCardRunConfig(
        aui.thread().composer().getState().runConfig,
        payload.agent_id,
        versioned
          ? {
              onAccepted: () => {
                setIsSubmitted(true);
                submitCard(cardKey);
              },
              onRejected: () =>
                setSummaryError(t("nl2agent.coverage.submitFailed")),
            }
          : undefined
      ),
      role: "user",
      content: [
        {
          type: "text",
          text: formatNl2AgentActionSummary(payload.subtype, t),
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
      ...(payload.card_id ? { card_id: payload.card_id } : {}),
      subtype: payload.subtype,
      agent_id: payload.agent_id,
      action: "retry_generation",
      result: versioned
        ? {
            card_id: payload.card_id,
            state_version: payload.state_version,
          }
        : { failed_fields: failedPromptFields },
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
  const requirementQueries = new Map(
    payload.requirements?.map(({ requirement_id, query }) => [
      requirement_id,
      query,
    ])
  );
  const renderResource = (
    item: BindingItemState,
    requirementId?: string,
    score?: number
  ) => {
    const ref = candidateRef(item);
    const tool =
      item.resource.candidate.resource_type === "tool"
        ? findCanonicalTool(availableTools, parseResourceId(ref, "tool"))
        : undefined;
    const ownsConfigDialog =
      !requirementId ||
      unifiedPayload?.requirements.find((row) =>
        row.covered_resources.some((resource) => resource.candidate_ref === ref)
      )?.requirement_id === requirementId;
    return (
      <Nl2AgentBindingItem
        key={ref}
        item={
          requirementId
            ? {
                ...item,
                selected:
                  item.bindingStatus === "bound" ||
                  (selections[requirementId] ?? []).includes(ref),
              }
            : item
        }
        matchScore={score}
        tool={tool}
        matchedRequirements={
          requirementId
            ? []
            : [
                ...new Set(
                  item.resource.candidate.requirement_ids
                    .map((id) => requirementQueries.get(id))
                    .filter((query): query is string => Boolean(query))
                ),
              ]
        }
        ui={{
          locked: isInteractionLocked,
          configurationLocked: areResourceOperationsLocked || isBinding,
          binding: isBinding,
          catalogFetching: isToolCatalogFetching,
          catalogError: isToolCatalogError,
          configLoading: loadingConfigRef === ref,
          configuring: configuringRef === ref && ownsConfigDialog,
          knowledgeLoading: knowledgeQuery.isFetching,
          knowledgeError: knowledgeQuery.isError,
        }}
        onToggle={() => {
          if (item.bindingStatus === "bound") return;
          if (!requirementId) {
            dispatch({ type: "toggle", ref });
            return;
          }
          const old = selections[requirementId] ?? [];
          const next = {
            ...selections,
            [requirementId]: old.includes(ref)
              ? old.filter((value) => value !== ref)
              : [...old, ref],
          };
          setSelections(next);
          dispatch({
            type: "set_selected",
            refs: new Set(Object.values(next).flat()),
          });
        }}
        onConfigure={() => void openResourceConfig(item, tool)}
        onCloseConfig={() => setConfiguringRef(null)}
        onRetryKnowledge={() => void knowledgeQuery.refetch()}
        onSaveKnowledge={(params) =>
          dispatch({ type: "save_config", ref, params, knowledgeEdited: true })
        }
      />
    );
  };

  const bindingFooter = (
    <footer className="border-t px-4 py-3">
      {summaryError ? (
        <p className="mb-3 text-xs text-destructive" role="alert">
          {summaryError}
        </p>
      ) : null}
      {unifiedPayload &&
      items.some((item) => item.resource.readiness === "not_ready") ? (
        <p className="mb-2 text-xs text-muted-foreground">
          {t("nl2agent.unified.fixExisting")}{" "}
          <Button
            variant="link"
            size="sm"
            className="h-auto p-0 text-xs"
            disabled={isInteractionLocked || isBinding}
            onClick={() => {
              aui.thread().append({
                role: "user",
                content: [
                  { type: "text", text: t("nl2agent.unified.refresh") },
                ],
                metadata: {
                  custom: {
                    nl2agentCardAction: {
                      type: "nl2agent_card_action",
                      subtype: "requirement_resources",
                      agent_id: payload.agent_id,
                      action: "confirm_requirements",
                      result: {
                        card_id: payload.card_id,
                        state_version: payload.state_version,
                        requirements: unifiedPayload.requirements.map(
                          ({ requirement_id, query }) => ({
                            requirement_id,
                            query,
                          })
                        ),
                      },
                    },
                  },
                },
                startRun: true,
                runConfig: nl2AgentCardRunConfig(
                  aui.thread().composer().getState().runConfig,
                  payload.agent_id,
                  {
                    onAccepted: () => {
                      preserveDraft();
                      submitCard(cardKey);
                    },
                    onRejected: () =>
                      setSummaryError(t("nl2agent.coverage.submitFailed")),
                  }
                ),
              });
            }}
          >
            {t("nl2agent.unified.refresh")}
          </Button>
        </p>
      ) : null}
      {unifiedPayload && !canContinue ? (
        <p role="status" className="mb-2 text-xs text-muted-foreground">
          {t("nl2agent.unified.continueBlocked")}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="ml-auto flex flex-wrap justify-end gap-2">
          {canRetryGeneration ? (
            <Button
              size="sm"
              className="h-7 px-2.5 py-0 text-xs"
              disabled={disabled}
              onClick={retryGeneration}
            >
              {t(
                "nl2agent.resourceBinding.retryGeneration",
                "Retry Prompt generation"
              )}
            </Button>
          ) : null}
          <Button
            size="sm"
            className="h-7 gap-1.5 px-2.5 py-0 text-xs [&_svg]:size-3.5"
            disabled={
              isInteractionLocked ||
              isBinding ||
              isSynchronizing ||
              (knowledgeQuery.isFetching &&
                selectedItems.some(
                  (item) =>
                    !item.knowledgeEdited &&
                    knowledgeToolName(
                      item.resource.candidate,
                      item.resource.candidate.resource_type === "tool"
                        ? findBindingTool(item, availableTools)
                        : undefined
                    )
                )) ||
              pendingSelected.length === 0
            }
            onClick={bindSelected}
          >
            {isBinding ? <Loader2 className="animate-spin" /> : null}
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
            size="sm"
            className="h-7 gap-1.5 px-2.5 py-0 text-xs disabled:bg-muted disabled:text-muted-foreground disabled:opacity-100 [&_svg]:size-3.5"
            disabled={
              canRetryGeneration ||
              isInteractionLocked ||
              !canContinue ||
              isSynchronizing ||
              loadingConfigRef !== null
            }
            onClick={continueFlow}
          >
            {isSynchronizing ? <Loader2 className="animate-spin" /> : null}
            {!unifiedPayload && selectedItems.length === 0
              ? t("nl2agent.resourceBinding.skip", "Skip")
              : t("nl2agent.resourceBinding.continue", "Continue")}
          </Button>
        </div>
      </div>
    </footer>
  );
  return (
    <section className="my-4 overflow-hidden rounded-2xl border border-border bg-white text-foreground shadow-sm dark:bg-card">
      {unifiedPayload ? (
        <RequirementCoverageCard
          payload={unifiedPayload}
          disabled={disabled}
          binding={{
            busy:
              isBinding ||
              loadingConfigRef !== null ||
              configuringRef !== null ||
              isSynchronizing,
            footer:
              unifiedPayload.purpose === "recommend" ? (
                <footer className="flex justify-end border-t px-4 py-3">
                  <Button
                    size="sm"
                    disabled={isInteractionLocked}
                    onClick={() => {
                      const action: Nl2AgentCardAction = {
                        type: "nl2agent_card_action",
                        subtype: "requirement_resources",
                        agent_id: payload.agent_id,
                        action: "use_recommendation",
                        result: {
                          card_id: payload.card_id,
                          state_version: payload.state_version,
                        },
                      };
                      aui.thread().append({
                        role: "user",
                        content: [
                          { type: "text", text: t("nl2agent.coverage.use") },
                        ],
                        metadata: { custom: { nl2agentCardAction: action } },
                        startRun: true,
                        runConfig: nl2AgentCardRunConfig(
                          aui.thread().composer().getState().runConfig,
                          payload.agent_id,
                          {
                            onAccepted: () => {
                              preserveDraft();
                              submitCard(cardKey);
                            },
                            onRejected: () =>
                              setSummaryError(
                                t("nl2agent.coverage.submitFailed")
                              ),
                          }
                        ),
                      });
                    }}
                  >
                    {t("nl2agent.coverage.use")}
                  </Button>
                </footer>
              ) : (
                bindingFooter
              ),
            onEditingChange: setRequirementEditing,
            onResourceBusyChange: setResourceOperationBusy,
            onAccepted: preserveDraft,
            status: (id) => {
              const row = unifiedPayload.requirements.find(
                (entry) => entry.requirement_id === id
              );
              const candidates = items.filter((item) =>
                row?.covered_resources.some(
                  (resource) => resource.candidate_ref === candidateRef(item)
                )
              );
              if (
                candidates.some(
                  (item) =>
                    item.bindingStatus === "bound" && hasValidKnowledge(item)
                )
              )
                return "ready";
              if (
                candidates.some((item) =>
                  (selections[id] ?? []).includes(candidateRef(item))
                )
              )
                return "pending";
              return row &&
                (row.covered_resources.length ||
                  row.installable_resources.length)
                ? "choose"
                : "unmatched";
            },
            renderResources: (id) => (
              <div className="overflow-hidden rounded-xl border divide-y">
                {unifiedPayload.requirements
                  .find((row) => row.requirement_id === id)
                  ?.covered_resources.map((resource) => {
                    const item = items.find(
                      (entry) => candidateRef(entry) === resource.candidate_ref
                    );
                    if (!item) return null;
                    const owner = unifiedPayload.requirements.find((row) =>
                      row.covered_resources.some(
                        (entry) =>
                          entry.candidate_ref === resource.candidate_ref
                      )
                    );
                    return (
                      <div key={resource.candidate_ref}>
                        {unifiedPayload.purpose === "recommend" ? (
                          <div className="px-3 py-2 text-xs">
                            <p
                              className="font-medium"
                              title={resource.candidate_ref}
                            >
                              {item.resource.candidate.name}{" "}
                              <span className="font-normal text-muted-foreground">
                                {item.resource.candidate.resource_type ===
                                "skill"
                                  ? "Skill"
                                  : item.resource.candidate.source ===
                                      "MCP_TOOL"
                                    ? "MCP"
                                    : "Local"}
                                {typeof resource.retrieval_score === "number"
                                  ? ` · ${Math.round(resource.retrieval_score * 100)}`
                                  : ""}
                              </span>
                            </p>
                            <p className="mt-1 text-muted-foreground">
                              {item.resource.candidate.description}
                            </p>
                          </div>
                        ) : (
                          renderResource(item, id, resource.retrieval_score)
                        )}
                        {owner && owner.requirement_id !== id ? (
                          <p className="px-4 pb-2 text-[11px] text-muted-foreground">
                            {t("nl2agent.unified.shared", {
                              query: owner.query,
                            })}
                          </p>
                        ) : null}
                      </div>
                    );
                  })}
              </div>
            ),
          }}
        />
      ) : (
        <>
          <div className="flex items-center gap-3 border-b px-4 py-3.5">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
              <Link2 className="size-4" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold">
                {t("nl2agent.resourceBinding.title", "Resource binding")}
              </h3>
              <p className="mt-0.5 text-xs leading-5 text-muted-foreground">
                {t(
                  "nl2agent.resourceBinding.description",
                  "Select relevant installed resources, configure them, then bind them together."
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
            <div className="divide-y">
              {pendingItems.map((item) => renderResource(item))}
            </div>
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
                  {t(
                    "nl2agent.resourceBinding.boundResources",
                    "Bound resources"
                  )}
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
                  {boundItems.map((item) => renderResource(item))}
                </div>
              ) : null}
            </div>
          ) : null}
        </>
      )}
      {!unifiedPayload && disabled ? (
        <p className="border-t px-4 py-3 text-xs text-muted-foreground">
          {t("nl2agent.unified.legacy")}
        </p>
      ) : !unifiedPayload ? (
        bindingFooter
      ) : null}

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
