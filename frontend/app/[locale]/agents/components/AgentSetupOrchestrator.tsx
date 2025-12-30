"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { TFunction } from "i18next";

import { App, Modal, Button, Tooltip, Row, Col } from "antd";
import { WarningFilled } from "@ant-design/icons";

import { TooltipProvider } from "@/components/ui/tooltip";
import {
  fetchAgentList,
  updateAgent,
  deleteAgent,
  exportAgent,
  searchAgentInfo,
  searchToolConfig,
  updateToolConfig,
} from "@/services/agentConfigService";
import { useAgentImport, ImportAgentData } from "@/hooks/useAgentImport";
import {
  Agent,
  AgentSetupOrchestratorProps,
  Tool,
  ToolParam,
} from "@/types/agentConfig";
import AgentImportWizard from "@/components/agent/AgentImportWizard";
import log from "@/lib/logger";
import { useConfirmModal } from "@/hooks/useConfirmModal";
import { useAuth } from "@/hooks/useAuth";

import SubAgentPool from "./agent/SubAgentPool";
import CollaborativeAgentDisplay from "./agent/CollaborativeAgentDisplay";
import { MemoizedToolPool } from "./tool/ToolPool";
import PromptManager from "./PromptManager";
import AgentCallRelationshipModal from "./agent/AgentCallRelationshipModal";
import SaveConfirmModal from "./SaveConfirmModal";

type PendingAction = () => void | Promise<void>;

/**
 * Agent Setup Orchestrator - Main coordination component for agent setup workflow
 */
export default function AgentSetupOrchestrator({
  businessLogic,
  setBusinessLogic,
  businessLogicError = false,
  selectedTools,
  setSelectedTools,
  isCreatingNewAgent,
  setIsCreatingNewAgent,
  mainAgentModel,
  setMainAgentModel,
  mainAgentModelId,
  setMainAgentModelId,
  mainAgentMaxStep,
  setMainAgentMaxStep,
  businessLogicModel,
  setBusinessLogicModel,
  businessLogicModelId,
  setBusinessLogicModelId,
  tools,
  subAgentList = [],
  loadingAgents = false,
  mainAgentId,
  setMainAgentId,
  setSubAgentList,
  enabledAgentIds,
  setEnabledAgentIds,
  onEditingStateChange,
  onToolsRefresh,
  dutyContent,
  setDutyContent,
  constraintContent,
  setConstraintContent,
  fewShotsContent,
  setFewShotsContent,
  agentName,
  setAgentName,
  agentDescription,
  setAgentDescription,
  agentDisplayName,
  setAgentDisplayName,
  agentAuthor,
  setAgentAuthor,
  isGeneratingAgent = false,
  // SystemPromptDisplay related props
  onDebug,
  getCurrentAgentId,
  onGenerateAgent,
  onExportAgent,
  onDeleteAgent,
  editingAgent: editingAgentFromParent,
  onExitCreation,
  isEmbeddingConfigured,
  onUnsavedChange,
  registerSaveHandler,
  registerReloadHandler,
}: AgentSetupOrchestratorProps) {
  const { user, isSpeedMode } = useAuth();
  const [enabledToolIds, setEnabledToolIds] = useState<number[]>([]);
  const [isLoadingTools, setIsLoadingTools] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [toolConfigDrafts, setToolConfigDrafts] = useState<
    Record<string, ToolParam[]>
  >({});
  const [pendingImportData, setPendingImportData] = useState<{
    agentInfo: any;
  } | null>(null);
  const [importingAction, setImportingAction] = useState<
    "force" | "regenerate" | null
  >(null);
  
  // Agent import wizard states
  const [importWizardVisible, setImportWizardVisible] = useState(false);
  const [importWizardData, setImportWizardData] = useState<ImportAgentData | null>(null);
  // Use generation state passed from parent component, not local state




  const lastProcessedAgentIdForEmbedding = useRef<number | null>(null);

  // Flag to track if we need to refresh enabledToolIds after tools update
  const shouldRefreshEnabledToolIds = useRef(false);
  // Track previous tools prop to detect when it's updated
  const previousToolsRef = useRef<Tool[] | undefined>(undefined);

  // Call relationship modal state
  const [callRelationshipModalVisible, setCallRelationshipModalVisible] =
    useState(false);

  // Edit agent related status
  const [isEditingAgent, setIsEditingAgent] = useState(false);
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);
  const activeEditingAgent = editingAgentFromParent || editingAgent;
  const isAgentUnavailable = activeEditingAgent?.is_available === false;
  const agentUnavailableReasons =
    isAgentUnavailable && Array.isArray(activeEditingAgent?.unavailable_reasons)
      ? (activeEditingAgent?.unavailable_reasons as string[])
      : [];
  const mergeAgentAvailabilityMetadata = useCallback(
    (detail: Agent, fallback?: Agent | null): Agent => {
      const detailReasons = Array.isArray(detail?.unavailable_reasons)
        ? detail.unavailable_reasons
        : [];
      const fallbackReasons = Array.isArray(fallback?.unavailable_reasons)
        ? fallback!.unavailable_reasons!
        : [];
      const normalizedReasons =
        detailReasons.length > 0 ? detailReasons : fallbackReasons;

      const normalizedAvailability =
        normalizedReasons.length > 0
          ? false
          : typeof detail?.is_available === "boolean"
          ? detail.is_available
          : typeof fallback?.is_available === "boolean"
          ? fallback.is_available
          : detail?.is_available;

      return {
        ...detail,
        unavailable_reasons: normalizedReasons,
        is_available: normalizedAvailability,
      };
    },
    []
  );

  const numericMainAgentId =
    mainAgentId !== null &&
    mainAgentId !== undefined &&
    String(mainAgentId).trim() !== ""
      ? Number(mainAgentId)
      : null;
  const hasPersistedMainAgentId =
    typeof numericMainAgentId === "number" &&
    !Number.isNaN(numericMainAgentId) &&
    numericMainAgentId > 0;
  const isDraftCreationSession =
    isCreatingNewAgent && !hasPersistedMainAgentId && !isEditingAgent;

  // Add a flag to track if it has been initialized to avoid duplicate calls
  const hasInitialized = useRef(false);
  // Baseline snapshot for change detection
  const baselineRef = useRef<any | null>(null);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(
    null
  );
  const [isSaveConfirmOpen, setIsSaveConfirmOpen] = useState(false);
  // When true, bypass unsaved-check to avoid reopening the confirm modal during a confirmed switch
  const skipUnsavedCheckRef = useRef(false);
  // Context for confirmation modal behavior
  const [confirmContext, setConfirmContext] = useState<"switch" | "exitCreate">(
    "switch"
  );

  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { confirm } = useConfirmModal();

  // Common refresh agent list function, moved to the front to avoid hoisting issues
  const refreshAgentList = async (t: TFunction, clearTools: boolean = true) => {
    if (clearTools) {
      setIsLoadingTools(true);
      // Clear the tool selection status when loading starts
      setSelectedTools([]);
      setEnabledToolIds([]);
    }

    try {
      const result = await fetchAgentList();
      if (result.success) {
        // Update agent list with basic info only
        setSubAgentList(result.data);
        // Removed success message to avoid duplicate notifications
      } else {
        message.error(
          result.message || t("businessLogic.config.error.agentListFailed")
        );
      }
    } catch (error) {
      log.error(t("agentConfig.agents.listFetchFailedDebug"), error);
      message.error(t("businessLogic.config.error.agentListFailed"));
    } finally {
      if (clearTools) {
        setIsLoadingTools(false);
      }
    }
  };
  // Build current snapshot for dirty detection
  const currentSnapshot = useMemo(
    () => ({
      agentId:
        (isEditingAgent && editingAgent ? editingAgent.id : mainAgentId) ??
        null,
      agentName: agentName || "",
      agentDescription: agentDescription || "",
      agentDisplayName: agentDisplayName || "",
      businessLogic: businessLogic || "",
      dutyContent: dutyContent || "",
      constraintContent: constraintContent || "",
      fewShotsContent: fewShotsContent || "",
      mainAgentModelId: mainAgentModelId ?? null,
      businessLogicModelId: businessLogicModelId ?? null,
      mainAgentMaxStep: Number(mainAgentMaxStep ?? 5),
      enabledAgentIds: Array.from(
        new Set(
          (enabledAgentIds || []).map((n) => Number(n)).filter((n) => !isNaN(n))
        )
      ).sort((a, b) => a - b),
      enabledToolIds: Array.from(
        new Set(
          (enabledToolIds || []).map((n) => Number(n)).filter((n) => !isNaN(n))
        )
      ).sort((a, b) => a - b),
      selectedToolIds: Array.from(
        new Set(
          (selectedTools || [])
            .map((t: any) => Number(t.id))
            .filter((id: number) => !isNaN(id))
        )
      ).sort((a, b) => a - b),
    }),
    [
      isEditingAgent,
      editingAgent,
      mainAgentId,
      agentName,
      agentDescription,
      agentDisplayName,
      businessLogic,
      dutyContent,
      constraintContent,
      fewShotsContent,
      mainAgentModelId,
      businessLogicModelId,
      mainAgentMaxStep,
      enabledAgentIds,
      enabledToolIds,
      selectedTools,
    ]
  );

  // Initialize baseline when entering edit mode or loading agent details
  useEffect(() => {
    if (isEditingAgent && editingAgent) {
      baselineRef.current = { ...currentSnapshot };
      setHasUnsavedChanges(false);
    }
  }, [isEditingAgent, editingAgent]);

  useEffect(() => {
    if (!isDraftCreationSession) {
      setToolConfigDrafts({});
    }
  }, [isDraftCreationSession]);

  // Initialize baseline when entering create mode so draft changes don't attach to previous agent
  useEffect(() => {
    if (isCreatingNewAgent && !isEditingAgent) {
      // Ensure state clears have applied, then capture a clean baseline
      setTimeout(() => {
        baselineRef.current = { ...currentSnapshot };
        setHasUnsavedChanges(false);
        onUnsavedChange?.(false);
      }, 0);
    }
  }, [isCreatingNewAgent, isEditingAgent, currentSnapshot, onUnsavedChange]);

  // Track changes to mark dirty
  useEffect(() => {
    if (!baselineRef.current) return;
    const b = baselineRef.current;
    const c = currentSnapshot;
    const shallowEqual =
      String(b.agentId ?? "") === String(c.agentId ?? "") &&
      b.agentName === c.agentName &&
      b.agentDescription === c.agentDescription &&
      b.agentDisplayName === c.agentDisplayName &&
      b.businessLogic === c.businessLogic &&
      b.dutyContent === c.dutyContent &&
      b.constraintContent === c.constraintContent &&
      b.fewShotsContent === c.fewShotsContent &&
      String(b.mainAgentModelId ?? "") === String(c.mainAgentModelId ?? "") &&
      String(b.businessLogicModelId ?? "") ===
        String(c.businessLogicModelId ?? "") &&
      Number(b.mainAgentMaxStep ?? 5) === Number(c.mainAgentMaxStep ?? 5) &&
      JSON.stringify(b.enabledAgentIds || []) ===
        JSON.stringify(c.enabledAgentIds || []) &&
      JSON.stringify(b.enabledToolIds || []) ===
        JSON.stringify(c.enabledToolIds || []) &&
      JSON.stringify(b.selectedToolIds || []) ===
        JSON.stringify(c.selectedToolIds || []);
    setHasUnsavedChanges(!shallowEqual);
    onUnsavedChange?.(!shallowEqual);
  }, [currentSnapshot]);

  // Reload current agent's complete data from backend
  const reloadCurrentAgentData = useCallback(async () => {
    const currentAgentId =
      (isEditingAgent && editingAgent ? editingAgent.id : mainAgentId) ?? null;

    if (!currentAgentId) {
      // If no agent ID, just reset unsaved state
      setHasUnsavedChanges(false);
      onUnsavedChange?.(false);
      return;
    }

    try {
      // Call query interface to get complete Agent information
      const result = await searchAgentInfo(Number(currentAgentId));

      if (!result.success || !result.data) {
        message.error(
          result.message || t("businessLogic.config.error.agentDetailFailed")
        );
        return;
      }

      const agentDetail = mergeAgentAvailabilityMetadata(
        result.data as Agent,
        editingAgent
      );
      setEditingAgent(agentDetail);

      // Reload all agent data to match backend state
      setAgentName?.(agentDetail.name || "");
      setAgentDescription?.(agentDetail.description || "");
      setAgentDisplayName?.(agentDetail.display_name || "");
      setAgentAuthor?.(agentDetail.author || "");

      // Load Agent data to interface
      setMainAgentModel(agentDetail.model);
      setMainAgentModelId(agentDetail.model_id ?? null);
      setMainAgentMaxStep(agentDetail.max_step);
      setBusinessLogic(agentDetail.business_description || "");
      setBusinessLogicModel(agentDetail.business_logic_model_name || null);
      setBusinessLogicModelId(agentDetail.business_logic_model_id || null);

      // Use backend returned sub_agent_id_list to set enabled agent list
      if (
        agentDetail.sub_agent_id_list &&
        agentDetail.sub_agent_id_list.length > 0
      ) {
        setEnabledAgentIds(
          agentDetail.sub_agent_id_list.map((id: any) => Number(id))
        );
      } else {
        setEnabledAgentIds([]);
      }

      // Load the segmented prompt content
      setDutyContent?.(agentDetail.duty_prompt || "");
      setConstraintContent?.(agentDetail.constraint_prompt || "");
      setFewShotsContent?.(agentDetail.few_shots_prompt || "");

      // Load Agent tools
      // Only set enabledToolIds, let useEffect sync selectedTools from tools array
      // This ensures tool objects in selectedTools match the structure in tools array
      if (agentDetail.tools && agentDetail.tools.length > 0) {
        // Set enabled tool IDs, ensure deduplication
        const toolIds = Array.from<number>(
          new Set(
            agentDetail.tools
              .map((tool: any) => Number(tool.id))
              .filter((id: number) => !isNaN(id))
          )
        ).sort((a, b) => a - b);
        setEnabledToolIds(toolIds);
        // Don't set selectedTools directly - let useEffect handle it based on enabledToolIds
        // This ensures tool objects match the structure from tools array
      } else {
        setEnabledToolIds([]);
        // Don't set selectedTools directly - let useEffect handle it
      }

      // Refresh agent list to ensure consistency, but don't clear tools to avoid flash
      await refreshAgentList(t, false);

      // Update baseline and reset unsaved state after reload
      // Use setTimeout to ensure state updates are processed before updating baseline
      setTimeout(() => {
        // Rebuild snapshot after state updates to get accurate baseline
        const updatedSnapshot = {
          agentId: Number(currentAgentId),
          agentName: agentDetail.name || "",
          agentDescription: agentDetail.description || "",
          agentDisplayName: agentDetail.display_name || "",
          businessLogic: agentDetail.business_description || "",
          dutyContent: agentDetail.duty_prompt || "",
          constraintContent: agentDetail.constraint_prompt || "",
          fewShotsContent: agentDetail.few_shots_prompt || "",
          mainAgentModelId: agentDetail.model_id ?? null,
          businessLogicModelId: agentDetail.business_logic_model_id ?? null,
          mainAgentMaxStep: Number(agentDetail.max_step ?? 5),
          enabledAgentIds: (agentDetail.sub_agent_id_list || [])
            .map((id: any) => Number(id))
            .sort(),
          enabledToolIds: Array.from<number>(
            new Set(
              (agentDetail.tools || [])
                .map((tool: any) => Number(tool.id))
                .filter((id: number) => !isNaN(id))
            )
          ).sort((a, b) => a - b),
          selectedToolIds: Array.from<number>(
            new Set(
              (agentDetail.tools || [])
                .map((tool: any) => Number(tool.id))
                .filter((id: number) => !isNaN(id))
            )
          ).sort((a, b) => a - b),
        };
        baselineRef.current = updatedSnapshot;
        setHasUnsavedChanges(false);
        onUnsavedChange?.(false);
      }, 200);
    } catch (error) {
      log.error(t("agentConfig.agents.detailsLoadFailed"), error);
      message.error(t("businessLogic.config.error.agentDetailFailed"));
      // Even on error, reset unsaved state
      setHasUnsavedChanges(false);
      onUnsavedChange?.(false);
    }
  }, [
    isEditingAgent,
    editingAgent,
    mainAgentId,
    currentSnapshot,
    t,
    refreshAgentList,
    onUnsavedChange,
  ]);

  // Expose a save function to be reused by confirm modal flows
  const saveAllChanges = useCallback(async () => {
    await handleSaveNewAgent(
      agentName || "",
      agentDescription || "",
      mainAgentModel,
      mainAgentMaxStep,
      businessLogic
    );
    // Reload data from backend after save to ensure consistency
    await reloadCurrentAgentData();
  }, [
    agentName,
    agentDescription,
    mainAgentModel,
    mainAgentMaxStep,
    businessLogic,
    reloadCurrentAgentData,
  ]);

  useEffect(() => {
    if (registerSaveHandler) {
      registerSaveHandler(saveAllChanges);
    }
  }, [registerSaveHandler, saveAllChanges]);

  useEffect(() => {
    if (registerReloadHandler) {
      registerReloadHandler(reloadCurrentAgentData);
    }
  }, [registerReloadHandler, reloadCurrentAgentData]);

  const confirmOrRun = useCallback(
    (action: PendingAction) => {
      // In creation mode, always show save confirmation dialog when clicking debug
      // Also show when there are unsaved changes
      if ((isCreatingNewAgent && !isEditingAgent) || hasUnsavedChanges) {
        setPendingAction(() => action);
        setConfirmContext("switch");
        setIsSaveConfirmOpen(true);
      } else {
        void Promise.resolve(action());
      }
    },
    [hasUnsavedChanges, isCreatingNewAgent, isEditingAgent]
  );

  const handleToolConfigDraftSave = useCallback(
    (updatedTool: Tool) => {
      if (!isDraftCreationSession) {
        return;
      }
      setToolConfigDrafts((prev) => ({
        ...prev,
        [updatedTool.id]:
          updatedTool.initParams?.map((param) => ({ ...param })) || [],
      }));
      setSelectedTools((prev: Tool[]) => {
        if (!prev || prev.length === 0) {
          return prev;
        }
        const index = prev.findIndex((tool) => tool.id === updatedTool.id);
        if (index === -1) {
          return prev;
        }
        const next = [...prev];
        next[index] = {
          ...updatedTool,
          initParams:
            updatedTool.initParams?.map((param) => ({ ...param })) || [],
        };
        return next;
      });
    },
    [isDraftCreationSession, setSelectedTools]
  );

  // Function to directly update enabledAgentIds
  const handleUpdateEnabledAgentIds = (newEnabledAgentIds: number[]) => {
    setEnabledAgentIds(newEnabledAgentIds);
  };

  // Removed creation-mode sub-agent fetch; creation is deferred until saving

  // Listen for changes in the creation of a new Agent
  useEffect(() => {
    if (isCreatingNewAgent) {
      if (!isEditingAgent) {
        // Clear configuration in creating mode
        setBusinessLogic("");
      } else {
        // In edit mode, data is loaded in handleEditAgent, here validate the form
      }
    } else {
      // When exiting the creation of a new Agent, reset the main Agent configuration
      // Only refresh list when exiting creation mode in non-editing mode to avoid flicker when exiting editing mode
      if (!isEditingAgent && hasInitialized.current) {
        setBusinessLogic("");
        setMainAgentModel(null);
        setMainAgentModelId(null);
        setMainAgentMaxStep(5);
        // Delay refreshing agent list to avoid jumping
        setTimeout(() => {
          refreshAgentList(t);
        }, 200);
      }
      // Sign that has been initialized
      hasInitialized.current = true;
    }
  }, [isCreatingNewAgent, isEditingAgent, mainAgentId]);

  const applyDraftParamsToTool = useCallback(
    (tool: Tool): Tool => {
      if (!isDraftCreationSession) {
        return tool;
      }
      const draft = toolConfigDrafts[tool.id];
      if (!draft || draft.length === 0) {
        return tool;
      }
      return {
        ...tool,
        initParams: draft.map((param) => ({ ...param })),
      };
    },
    [isDraftCreationSession, toolConfigDrafts]
  );

  // Listen for changes in the tool status, update the selected tool
  useEffect(() => {
    if (!tools || isLoadingTools) return;
    // Allow empty enabledToolIds array (it's valid when no tools are selected)
    if (enabledToolIds === undefined || enabledToolIds === null) return;

    // Filter out unavailable tools (is_available === false) to prevent deleted MCP tools from showing
    const enabledTools = tools
      .filter(
        (tool) =>
          enabledToolIds.includes(Number(tool.id)) &&
          tool.is_available !== false
      )
      .map((tool) => applyDraftParamsToTool(tool));

    setSelectedTools(enabledTools);
  }, [
    tools,
    enabledToolIds,
    isLoadingTools,
    applyDraftParamsToTool,
    setSelectedTools,
  ]);

  // Auto-unselect knowledge_base_search if embedding is not configured
  useEffect(() => {
    if (isEmbeddingConfigured) return;
    if (!tools || tools.length === 0) return;

    const kbTool = tools.find((tool) => tool.name === "knowledge_base_search");
    if (!kbTool) return;

    const currentAgentId = (
      isEditingAgent && editingAgent
        ? Number(editingAgent.id)
        : mainAgentId
        ? Number(mainAgentId)
        : undefined
    ) as number | undefined;

    if (!currentAgentId) return;
    if (lastProcessedAgentIdForEmbedding.current === currentAgentId) return;

    const kbToolId = Number(kbTool.id);
    if (!enabledToolIds || !enabledToolIds.includes(kbToolId)) {
      lastProcessedAgentIdForEmbedding.current = currentAgentId;
      return;
    }

    const run = async () => {
      try {
        // Fetch existing params to avoid losing saved configuration
        const search = await searchToolConfig(kbToolId, currentAgentId);
        const params =
          search.success && search.data?.params ? search.data.params : {};
        // Disable the tool
        await updateToolConfig(kbToolId, currentAgentId, params, false);
        // Update local state
        setEnabledToolIds((prev) => prev.filter((id) => id !== kbToolId));
        const nextSelected = selectedTools.filter(
          (tool) => tool.id !== kbTool.id
        );
        setSelectedTools(nextSelected);
      } catch (error) {
        // Even if API fails, still inform user and prevent usage in UI
      } finally {
        confirm({
          title: t("embedding.agentToolAutoDeselectModal.title"),
          content: t("embedding.agentToolAutoDeselectModal.content"),
          okText: t("common.confirm"),
          onOk: () => {},
        });
        lastProcessedAgentIdForEmbedding.current = currentAgentId;
      }
    };

    run();
  }, [
    isEmbeddingConfigured,
    tools,
    enabledToolIds,
    isEditingAgent,
    editingAgent,
    mainAgentId,
  ]);

  // Listen for refresh agent list events from parent component
  useEffect(() => {
    const handleRefreshAgentList = () => {
      refreshAgentList(t);
    };

    window.addEventListener("refreshAgentList", handleRefreshAgentList);

    return () => {
      window.removeEventListener("refreshAgentList", handleRefreshAgentList);
    };
  }, [t]);

  // Listen for tools updated events and refresh enabledToolIds if agent is selected
  useEffect(() => {
    const handleToolsUpdated = async () => {
      // If there's a selected agent (mainAgentId or editingAgent), refresh enabledToolIds
      const currentAgentId = (isEditingAgent && editingAgent
        ? Number(editingAgent.id)
        : mainAgentId
        ? Number(mainAgentId)
        : undefined) as number | undefined;

      if (currentAgentId) {
        try {
          // First, refresh the tools list to ensure it's up to date
          // Pass false to prevent showing success message (MCP modal will show its own message)
          if (onToolsRefresh) {
            // First, synchronize the selected tools once using search_info.
            await refreshAgentToolSelectionsFromServer(currentAgentId);
            // Then refresh the tool list
            await onToolsRefresh(false);
            // Wait for React state to update and tools prop to be updated
            // Use setTimeout to ensure tools prop is updated before refreshing enabledToolIds
            await new Promise((resolve) => setTimeout(resolve, 300));
            // Set flag to refresh enabledToolIds after tools prop updates
            shouldRefreshEnabledToolIds.current = true;
          }
        } catch (error) {
          log.error("Failed to refresh tools after tools update:", error);
        }
      }
    };

    window.addEventListener("toolsUpdated", handleToolsUpdated);

    return () => {
      window.removeEventListener("toolsUpdated", handleToolsUpdated);
    };
  }, [mainAgentId, isEditingAgent, editingAgent, onToolsRefresh, t]);

  const refreshAgentToolSelectionsFromServer = useCallback(
    async (agentId: number) => {
      try {
        const agentInfoResult = await searchAgentInfo(agentId);
        if (agentInfoResult.success && agentInfoResult.data) {
          const remoteTools = Array.isArray(agentInfoResult.data.tools)
            ? agentInfoResult.data.tools
            : [];
          const enabledIdsFromServer = remoteTools
            .filter(
              (remoteTool: any) =>
                remoteTool && remoteTool.is_available !== false
            )
            .map((remoteTool: any) => Number(remoteTool.id))
            .filter((id) => !Number.isNaN(id));

          const filteredIds = enabledIdsFromServer.filter((toolId) => {
            const toolMeta = tools?.find(
              (tool) => Number(tool.id) === Number(toolId)
            );
            return toolMeta && toolMeta.is_available !== false;
          });

          const dedupedIds = Array.from(new Set(filteredIds));
          setEnabledToolIds(dedupedIds);
          log.info("Refreshed agent tool selection from search_info", {
            agentId,
            toolIds: dedupedIds,
          });
        } else {
          log.error(
            "Failed to refresh agent tool selection via search_info",
            agentInfoResult.message
          );
        }
      } catch (error) {
        log.error(
          "Failed to refresh agent tool selection via search_info:",
          error
        );
      }
    },
    [tools, setEnabledToolIds, setSelectedTools]
  );

  // Refresh enabledToolIds when tools prop updates after toolsUpdated event
  useEffect(() => {
    const prevTools = previousToolsRef.current;
    const haveTools = tools && tools.length > 0;
    const prevLen = prevTools?.length ?? 0;
    const currLen = tools?.length ?? 0;
    const idsChanged =
      prevTools === undefined ||
      JSON.stringify(prevTools?.map((t) => t.id).sort()) !==
        JSON.stringify((tools || []).map((t) => t.id).sort());
    const grew = currLen > prevLen;

    // Always update the previous ref for future comparisons
    previousToolsRef.current = tools;

    // If there are no tools, nothing to do
    if (!haveTools) {
      return;
    }

    const currentAgentId = (isEditingAgent && editingAgent
      ? Number(editingAgent.id)
      : mainAgentId
      ? Number(mainAgentId)
      : undefined) as number | undefined;

    if (!currentAgentId) {
      shouldRefreshEnabledToolIds.current = false;
      return;
    }

    const refreshEnabledToolIds = async () => {
      try {
        // Small delay to allow tools prop to stabilize after updates
        await new Promise((resolve) => setTimeout(resolve, 50));
        await refreshAgentToolSelectionsFromServer(currentAgentId);
      } catch (error) {
        log.error(
          "Failed to refresh enabled tool IDs after tools update:",
          error
        );
      }
      shouldRefreshEnabledToolIds.current = false;
    };

    // Trigger when:
    // 1) We explicitly flagged a refresh after a toolsUpdated event, OR
    // 2) The tool list grew (e.g., an MCP tool was added) or IDs changed,
    //    which indicates the available tool set has changed and we should re-sync
    if (shouldRefreshEnabledToolIds.current || grew || idsChanged) {
      // Optimistically update selected tools to reduce perceived delay/flicker
      if (haveTools && Array.isArray(enabledToolIds) && enabledToolIds.length > 0) {
        try {
          const optimisticSelected = (tools || []).filter((tool) =>
            enabledToolIds.includes(Number(tool.id))
          );
          setSelectedTools(optimisticSelected);
        } catch (e) {
          log.warn("Optimistic selection update failed; will rely on refresh", e);
        }
      }
      refreshEnabledToolIds();
    }
  }, [
    tools,
    mainAgentId,
    isEditingAgent,
    editingAgent,
    enabledToolIds,
    refreshAgentToolSelectionsFromServer,
  ]);

  // Immediately reflect UI selection from enabledToolIds and latest tools (no server wait)
  useEffect(() => {
    const haveTools = Array.isArray(tools) && tools.length > 0;
    if (!haveTools) {
      setSelectedTools([]);
      return;
    }
    if (!Array.isArray(enabledToolIds) || enabledToolIds.length === 0) {
      setSelectedTools([]);
      return;
    }
    try {
      const nextSelected = (tools || []).filter((tool) =>
        enabledToolIds.includes(Number(tool.id))
      );
      setSelectedTools(nextSelected);
    } catch (e) {
      log.warn("Failed to sync selectedTools from enabledToolIds", e);
    }
  }, [enabledToolIds, tools, setSelectedTools]);

  // When tools change, sanitize enabledToolIds against availability to prevent transient flicker
  useEffect(() => {
    if (!Array.isArray(tools) || tools.length === 0) {
      return;
    }
    if (!Array.isArray(enabledToolIds)) {
      return;
    }
    const availableIdSet = new Set(
      (tools || [])
        .filter((t) => t && t.is_available !== false)
        .map((t) => Number(t.id))
        .filter((id) => !Number.isNaN(id))
    );
    const sanitized = enabledToolIds.filter((id) => availableIdSet.has(Number(id)));
    if (
      sanitized.length !== enabledToolIds.length ||
      sanitized.some((id, idx) => Number(id) !== Number(enabledToolIds[idx]))
    ) {
      setEnabledToolIds(sanitized);
    }
  }, [tools, enabledToolIds, setEnabledToolIds]);

  // Handle the creation of a new Agent
  const handleCreateNewAgent = async () => {
    // Set to create mode
    setIsEditingAgent(false);
    setEditingAgent(null);
    setIsCreatingNewAgent(true);

    // Clear all content when creating new agent to avoid showing cached data
    setBusinessLogic("");
    setDutyContent?.("");
    setConstraintContent?.("");
    setFewShotsContent?.("");
    setAgentName?.("");
    setAgentDescription?.("");
    setAgentDisplayName?.("");
    setAgentAuthor?.("");
    setAgentAuthor?.("");

    // Clear tool and agent selections
    setSelectedTools([]);
    setEnabledToolIds([]);
    setEnabledAgentIds([]);
    setToolConfigDrafts({});
    setMainAgentId?.(null);

    // Clear business logic model to allow default from global settings
    // The useEffect in PromptManager will set it to the default from localStorage
    setBusinessLogicModel(null);
    setBusinessLogicModelId(null);

    // Clear main agent model selection to trigger default model selection
    // The useEffect in AgentConfigModal will set it to the default from localStorage
    setMainAgentModel(null);
    setMainAgentModelId(null);

    try {
      await onToolsRefresh?.(false);
    } catch (error) {
      log.error("Failed to refresh tools in creation mode:", error);
    }

    onEditingStateChange?.(false, null);
  };

  // Reset the status when the user cancels the creation of an Agent
  const handleCancelCreating = async () => {
    // First notify external editing state change to avoid UI jumping
    onEditingStateChange?.(false, null);

    // Delay resetting state to let UI complete state switching first
    setTimeout(() => {
      // Use the parent's exit creation handler to properly clear cache
      if (onExitCreation) {
        onExitCreation();
      } else {
        setIsCreatingNewAgent(false);
      }
      setIsEditingAgent(false);
      setEditingAgent(null);

      // Clear the mainAgentId
      setMainAgentId(null);

      // Note: Content clearing is handled by onExitCreation above
      // Delay clearing tool and collaborative agent selection to avoid jumping
      setTimeout(() => {
        setSelectedTools([]);
        setEnabledToolIds([]);
        setEnabledAgentIds([]);
      }, 200);
      // Reset unsaved state and baseline
      baselineRef.current = null;
      setHasUnsavedChanges(false);
      onUnsavedChange?.(false);
    }, 100);
  };

  // Handle exit edit mode
  const handleExitEditMode = async () => {
    if (isCreatingNewAgent) {
      // If in creation mode, check unsaved changes first
      if (hasUnsavedChanges) {
        setConfirmContext("exitCreate");
        setPendingAction(null);
        setIsSaveConfirmOpen(true);
        return;
      }
      await handleCancelCreating();
    } else if (isEditingAgent) {
      // If in editing mode, clear related states first, then update editing state to avoid flickering
      // First clear tool and agent selection states
      setSelectedTools([]);
      setEnabledToolIds([]);
      setEnabledAgentIds([]);

      // Clear right-side name description box
      setAgentName?.("");
      setAgentDescription?.("");

      // Clear business logic
      setBusinessLogic("");

      // Clear segmented prompt content
      setDutyContent?.("");
      setConstraintContent?.("");
      setFewShotsContent?.("");

      // Notify external editing state change
      onEditingStateChange?.(false, null);

      // Finally update editing state to avoid triggering refresh logic in useEffect
      setIsEditingAgent(false);
      setEditingAgent(null);
      setMainAgentId(null);

      // Ensure tool pool won't show loading state
      setIsLoadingTools(false);

      // Reset unsaved state and baseline when explicitly exiting edit mode
      baselineRef.current = null;
      setHasUnsavedChanges(false);
      onUnsavedChange?.(false);
    }
  };

  // Handle the creation of a new Agent
  const persistDraftToolConfigs = useCallback(
    async (agentId: number, toolIdsToEnable: number[]) => {
      if (!toolIdsToEnable || toolIdsToEnable.length === 0) {
        return;
      }

      const payloads = toolIdsToEnable
        .map((toolId) => {
          const toolIdStr = String(toolId);
          const draftParams = toolConfigDrafts[toolIdStr];
          const baseTool =
            selectedTools.find((tool) => Number(tool.id) === toolId) ||
            tools.find((tool) => Number(tool.id) === toolId);
          const paramsSource =
            (draftParams && draftParams.length > 0
              ? draftParams
              : baseTool?.initParams) || [];
          if (!paramsSource || paramsSource.length === 0) {
            return null;
          }
          const params = paramsSource.reduce((acc, param) => {
            acc[param.name] = param.value;
            return acc;
          }, {} as Record<string, any>);
          return {
            toolId,
            params,
          };
        })
        .filter(Boolean) as Array<{
        toolId: number;
        params: Record<string, any>;
      }>;

      if (payloads.length === 0) {
        return;
      }

      let persistError = false;
      for (const payload of payloads) {
        try {
          await updateToolConfig(payload.toolId, agentId, payload.params, true);
        } catch (error) {
          persistError = true;
          log.error("Failed to persist tool configuration for new agent:", error);
        }
      }

      if (persistError) {
        message.error(t("toolConfig.message.saveError"));
      }
    },
    [toolConfigDrafts, selectedTools, tools, message, t]
  );

  const handleSaveNewAgent = async (
    name: string,
    description: string,
    model: string | null,
    max_step: number,
    business_description: string
  ) => {
    if (name.trim()) {
      try {
        let result;

        // Generate deduplicated enabledToolIds from selectedTools to ensure consistency
        const deduplicatedToolIds = Array.from(
          new Set(
            (selectedTools || [])
              .map((tool) => Number(tool.id))
              .filter((id) => !isNaN(id))
          )
        ).sort((a, b) => a - b);

        // Generate deduplicated enabledAgentIds to ensure consistency
        const deduplicatedAgentIds = Array.from(
          new Set(
            (enabledAgentIds || [])
              .map((id) => Number(id))
              .filter((id) => !isNaN(id))
          )
        ).sort((a, b) => a - b);

        // Determine author value: use provided author, or default to user email in Full mode
        const finalAuthor = agentAuthor || (!isSpeedMode && user?.email ? user.email : undefined);

        if (isEditingAgent && editingAgent) {
          // Editing existing agent
          result = await updateAgent(
            Number(editingAgent.id),
            name,
            description,
            model === null ? undefined : model,
            max_step,
            false,
            true,
            business_description,
            dutyContent,
            constraintContent,
            fewShotsContent,
            agentDisplayName,
            mainAgentModelId ?? undefined,
            businessLogicModel ?? undefined,
            businessLogicModelId ?? undefined,
            deduplicatedToolIds,
            deduplicatedAgentIds,
            finalAuthor
          );
        } else {
          // Creating new agent on save
          result = await updateAgent(
            undefined,
            name,
            description,
            model === null ? undefined : model,
            max_step,
            false,
            true,
            business_description,
            dutyContent,
            constraintContent,
            fewShotsContent,
            agentDisplayName,
            mainAgentModelId ?? undefined,
            businessLogicModel ?? undefined,
            businessLogicModelId ?? undefined,
            deduplicatedToolIds,
            deduplicatedAgentIds,
            finalAuthor
          );
        }

        if (result.success) {
          if (!isEditingAgent && result.data?.agent_id) {
            await persistDraftToolConfigs(
              Number(result.data.agent_id),
              deduplicatedToolIds
            );
            setToolConfigDrafts({});
          }
          // If created, set new mainAgentId for subsequent operations
          if (!isEditingAgent && result.data?.agent_id) {
            setMainAgentId(String(result.data.agent_id));
          }
          message.success(t("businessLogic.config.message.agentSaveSuccess"));

          // Reset unsaved changes state to remove blue indicator
          setHasUnsavedChanges(false);
          onUnsavedChange?.(false);

          // If editing existing agent, reload data and maintain edit state
          if (isEditingAgent && editingAgent) {
            // Reload agent data to sync with backend
            await reloadCurrentAgentData();
          } else if (result.data?.agent_id) {
            // On create success: auto-select and enter edit mode for the new agent
            const newId = Number(result.data.agent_id);
            try {
              const detail = await searchAgentInfo(newId);
              if (detail.success && detail.data) {
                const agentDetail = mergeAgentAvailabilityMetadata(
                  detail.data as Agent
                );
                setIsEditingAgent(true);
                setEditingAgent(agentDetail);
                setMainAgentId(agentDetail.id);
                setIsCreatingNewAgent(false);
                // Populate UI fields
                setAgentName?.(agentDetail.name || "");
                setAgentDescription?.(agentDetail.description || "");
                setAgentDisplayName?.(agentDetail.display_name || "");
                setAgentAuthor?.(agentDetail.author || "");
                onEditingStateChange?.(true, agentDetail);
                setMainAgentModel(agentDetail.model);
                setMainAgentModelId(agentDetail.model_id ?? null);
                setMainAgentMaxStep(agentDetail.max_step);
                setBusinessLogic(agentDetail.business_description || "");
                setBusinessLogicModel(
                  agentDetail.business_logic_model_name || null
                );
                setBusinessLogicModelId(
                  agentDetail.business_logic_model_id || null
                );
                if (
                  agentDetail.sub_agent_id_list &&
                  agentDetail.sub_agent_id_list.length > 0
                ) {
                  setEnabledAgentIds(
                    agentDetail.sub_agent_id_list.map((id: any) => Number(id))
                  );
                } else {
                  setEnabledAgentIds([]);
                }
                setDutyContent?.(agentDetail.duty_prompt || "");
                setConstraintContent?.(agentDetail.constraint_prompt || "");
                setFewShotsContent?.(agentDetail.few_shots_prompt || "");
                if (agentDetail.tools && agentDetail.tools.length > 0) {
                  setSelectedTools(agentDetail.tools);
                  setEnabledToolIds(
                    agentDetail.tools
                      .map((tool: any) => Number(tool.id))
                      .filter((id: number) => !isNaN(id)) as number[]
                  );
                } else {
                  setSelectedTools([]);
                  setEnabledToolIds([]);
                }
                // Establish clean baseline for the freshly created agent to avoid modal on switch
                setTimeout(() => {
                  baselineRef.current = {
                    agentId: agentDetail.id,
                    agentName: agentDetail.name || "",
                    agentDescription: agentDetail.description || "",
                    agentDisplayName: agentDetail.display_name || "",
                    businessLogic: agentDetail.business_description || "",
                    dutyContent: agentDetail.duty_prompt || "",
                    constraintContent: agentDetail.constraint_prompt || "",
                    fewShotsContent: agentDetail.few_shots_prompt || "",
                    mainAgentModelId: agentDetail.model_id ?? null,
                    businessLogicModelId:
                      agentDetail.business_logic_model_id ?? null,
                    mainAgentMaxStep: Number(agentDetail.max_step ?? 5),
                    enabledAgentIds: Array.from(
                      new Set(
                        (agentDetail.sub_agent_id_list || [])
                          .map((n: any) => Number(n))
                          .filter((n: number) => !isNaN(n))
                      )
                    ) as number[],
                    enabledToolIds: Array.from(
                      new Set(
                        (agentDetail.tools || [])
                          .map((t: any) => Number(t.id))
                          .filter((id: number) => !isNaN(id))
                      )
                    ) as number[],
                    selectedToolIds: Array.from(
                      new Set(
                        (agentDetail.tools || [])
                          .map((t: any) => Number(t.id))
                          .filter((id: number) => !isNaN(id))
                      )
                    ) as number[],
                  } as any;
                  setHasUnsavedChanges(false);
                  onUnsavedChange?.(false);
                }, 0);
              } else {
                // Fallback: set minimal selection
                setIsEditingAgent(true);
                setEditingAgent({ id: newId } as any);
                setMainAgentId(String(newId));
                setIsCreatingNewAgent(false);
                setHasUnsavedChanges(false);
                onUnsavedChange?.(false);
              }
            } catch {
              setIsEditingAgent(true);
              setEditingAgent({ id: newId } as any);
              setMainAgentId(String(newId));
              setIsCreatingNewAgent(false);
              setHasUnsavedChanges(false);
              onUnsavedChange?.(false);
            }
          }

          // Refresh agent list and keep tools intact to avoid flashing
          refreshAgentList(t, false);
        } else {
          message.error(
            result.message || t("businessLogic.config.error.saveFailed")
          );
        }
      } catch (error) {
        log.error("Error saving agent:", error);
        message.error(t("businessLogic.config.error.saveRetry"));
      }
    } else {
      if (!name.trim()) {
        message.error(t("businessLogic.config.error.nameEmpty"));
      }
      if (!mainAgentId) {
        message.error(t("businessLogic.config.error.noAgentId"));
      }
    }
  };

  const handleSaveAgent = () => {
    // The save button's disabled state is controlled by canSaveAgent, which already validates the required fields.
    // We can still add checks here for better user feedback in case the function is triggered unexpectedly.
    if (!agentName || agentName.trim() === "") {
      message.warning(t("businessLogic.config.message.completeAgentInfo"));
      return;
    }

    if (!mainAgentModel) {
      message.warning(t("businessLogic.config.message.selectModelRequired"));
      return;
    }

    const hasPromptContent =
      dutyContent?.trim() ||
      constraintContent?.trim() ||
      fewShotsContent?.trim();
    if (!hasPromptContent) {
      message.warning(t("businessLogic.config.message.generatePromptFirst"));
      return;
    }

    // Always use agentName and agentDescription as they are bound to the inputs in both create and edit modes.
    handleSaveNewAgent(
      agentName,
      agentDescription || "",
      mainAgentModel,
      mainAgentMaxStep,
      businessLogic
    );
  };

  const handleEditAgent = async (agent: Agent, t: TFunction) => {
    // Check for unsaved changes before switching agents (unless bypass flag set)
    if (hasUnsavedChanges && !skipUnsavedCheckRef.current) {
      setPendingAction(() => () => handleEditAgent(agent, t));
      setIsSaveConfirmOpen(true);
      return;
    }

    try {
      // Call query interface to get complete Agent information
      const result = await searchAgentInfo(Number(agent.id));

      if (!result.success || !result.data) {
        message.error(
          result.message || t("businessLogic.config.error.agentDetailFailed")
        );
        return;
      }

      const agentDetail = mergeAgentAvailabilityMetadata(
        result.data as Agent,
        agent
      );

      // Set editing state and highlight after successfully getting information
      setIsEditingAgent(true);
      setEditingAgent(agentDetail);
      // Set mainAgentId to current editing Agent ID
      setMainAgentId(agentDetail.id);
      // When editing existing agent, ensure exit creation mode AFTER setting all data
      // Use setTimeout to ensure all data is set before triggering useEffect
      setTimeout(() => {
        setIsCreatingNewAgent(false);
      }, 100); // Increase delay to ensure state updates are processed

      // First set right-side name description box data to ensure immediate display

      setAgentName?.(agentDetail.name || "");
      setAgentDescription?.(agentDetail.description || "");
      setAgentDisplayName?.(agentDetail.display_name || "");
      setAgentAuthor?.(agentDetail.author || "");

      // Notify external editing state change (use complete data)
      onEditingStateChange?.(true, agentDetail);

      // Load Agent data to interface
      setMainAgentModel(agentDetail.model);
      setMainAgentModelId(agentDetail.model_id ?? null);
      setMainAgentMaxStep(agentDetail.max_step);
      setBusinessLogic(agentDetail.business_description || "");
      setBusinessLogicModel(agentDetail.business_logic_model_name || null);
      setBusinessLogicModelId(agentDetail.business_logic_model_id || null);

      // Use backend returned sub_agent_id_list to set enabled agent list
      if (
        agentDetail.sub_agent_id_list &&
        agentDetail.sub_agent_id_list.length > 0
      ) {
        setEnabledAgentIds(
          agentDetail.sub_agent_id_list.map((id: any) => Number(id))
        );
      } else {
        setEnabledAgentIds([]);
      }

      // Load the segmented prompt content
      setDutyContent?.(agentDetail.duty_prompt || "");
      setConstraintContent?.(agentDetail.constraint_prompt || "");
      setFewShotsContent?.(agentDetail.few_shots_prompt || "");

      // Load Agent tools
      // Filter out unavailable tools (is_available === false) to prevent deleted MCP tools from showing
      if (agentDetail.tools && agentDetail.tools.length > 0) {
        const availableTools = agentDetail.tools.filter(
          (tool: any) => tool.is_available !== false
        );
        const toolIds = Array.from<number>(
          new Set(
            availableTools
              .map((tool: any) => Number(tool.id))
              .filter((id: number) => !isNaN(id))
          )
        ).sort((a, b) => a - b);
        setSelectedTools(availableTools);
        setEnabledToolIds(toolIds);
      } else {
        setSelectedTools([]);
        setEnabledToolIds([]);
      }
    } catch (error) {
      log.error(t("agentConfig.agents.detailsLoadFailed"), error);
      message.error(t("businessLogic.config.error.agentDetailFailed"));
      // If error occurs, reset editing state
      setIsEditingAgent(false);
      setEditingAgent(null);
      // Note: Don't reset isCreatingNewAgent, keep agent pool display
      onEditingStateChange?.(false, null);
    }
  };

  // Handle the update of the model
  // Handle Business Logic Model change
  const handleBusinessLogicModelChange = (value: string, modelId?: number) => {
    setBusinessLogicModel(value);
    if (modelId !== undefined) {
      setBusinessLogicModelId(modelId);
    }
  };

  const handleModelChange = async (value: string, modelId?: number) => {
    const targetAgentId =
      isEditingAgent && editingAgent ? editingAgent.id : mainAgentId;

    // Update local state first
    setMainAgentModel(value);
    if (modelId !== undefined) {
      setMainAgentModelId(modelId);
    }

    // If no agent ID yet (e.g., during initial creation setup), just update local state
    // The model will be saved when the agent is fully created
    // Also skip update API call if in create mode (agent not saved yet)
    if (!targetAgentId || isCreatingNewAgent) {
      return;
    }

    // Call updateAgent API to save the model change
    try {
      const result = await updateAgent(
        Number(targetAgentId),
        undefined, // name
        undefined, // description
        value, // modelName
        undefined, // maxSteps
        undefined, // provideRunSummary
        undefined, // enabled
        undefined, // businessDescription
        undefined, // dutyPrompt
        undefined, // constraintPrompt
        undefined, // fewShotsPrompt
        undefined, // displayName
        modelId, // modelId
        undefined, // businessLogicModelName
        undefined, // businessLogicModelId
        undefined // enabledToolIds
      );

      if (!result.success) {
        message.error(
          result.message || t("businessLogic.config.error.modelUpdateFailed")
        );
        // Revert local state on failure
        setMainAgentModel(mainAgentModel);
        setMainAgentModelId(mainAgentModelId);
      }
    } catch (error) {
      log.error("Error updating agent model:", error);
      message.error(t("businessLogic.config.error.modelUpdateFailed"));
      // Revert local state on failure
      setMainAgentModel(mainAgentModel);
      setMainAgentModelId(mainAgentModelId);
    }
  };

  // Handle the update of the maximum number of steps
  const handleMaxStepChange = async (value: number | null) => {
    const targetAgentId =
      isEditingAgent && editingAgent ? editingAgent.id : mainAgentId;

    const newValue = value ?? 5;

    // Update local state first
    setMainAgentMaxStep(newValue);

    // If no agent ID yet (e.g., during initial creation setup), just update local state
    // The max steps will be saved when the agent is fully created
    // Also skip update API call if in create mode (agent not saved yet)
    if (!targetAgentId || isCreatingNewAgent) {
      return;
    }

    // Call updateAgent API to save the max steps change
    try {
      const result = await updateAgent(
        Number(targetAgentId),
        undefined, // name
        undefined, // description
        undefined, // modelName
        newValue, // maxSteps
        undefined, // provideRunSummary
        undefined, // enabled
        undefined, // businessDescription
        undefined, // dutyPrompt
        undefined, // constraintPrompt
        undefined, // fewShotsPrompt
        undefined, // displayName
        undefined, // modelId
        undefined, // businessLogicModelName
        undefined, // businessLogicModelId
        undefined // enabledToolIds
      );

      if (!result.success) {
        message.error(
          result.message || t("businessLogic.config.error.maxStepsUpdateFailed")
        );
        // Revert local state on failure
        setMainAgentMaxStep(mainAgentMaxStep);
      }
    } catch (error) {
      log.error("Error updating agent max steps:", error);
      message.error(t("businessLogic.config.error.maxStepsUpdateFailed"));
      // Revert local state on failure
      setMainAgentMaxStep(mainAgentMaxStep);
    }
  };

  // Use unified import hooks - one for normal import, one for force import
  const { importFromData: runNormalImport } = useAgentImport({
    onSuccess: () => {
      message.success(t("businessLogic.config.error.agentImportSuccess"));
      refreshAgentList(t, false);
    },
    onError: (error) => {
      log.error(t("agentConfig.agents.importFailed"), error);
      message.error(t("businessLogic.config.error.agentImportFailed"));
    },
    forceImport: false,
  });

  const { importFromData: runForceImport } = useAgentImport({
    onSuccess: () => {
      message.success(t("businessLogic.config.error.agentImportSuccess"));
      refreshAgentList(t, false);
    },
    onError: (error) => {
      log.error(t("agentConfig.agents.importFailed"), error);
      message.error(t("businessLogic.config.error.agentImportFailed"));
    },
    forceImport: true,
  });

  const runAgentImport = useCallback(
    async (
      agentPayload: any,
      options?: { forceImport?: boolean }
    ) => {
      setIsImporting(true);
      try {
        if (options?.forceImport) {
          await runForceImport(agentPayload);
        } else {
          await runNormalImport(agentPayload);
        }
        return true;
      } catch (error) {
        return false;
      } finally {
        setIsImporting(false);
      }
    },
    [runNormalImport, runForceImport]
  );

  // Handle importing agent - use AgentImportWizard for ExportAndImportDataFormat
  const handleImportAgent = (t: TFunction) => {
    // Create a hidden file input element
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = ".json";
    fileInput.onchange = async (event) => {
      setPendingImportData(null);
      const file = (event.target as HTMLInputElement).files?.[0];
      if (!file) return;

      // Check file type
      if (!file.name.endsWith(".json")) {
        message.error(t("businessLogic.config.error.invalidFileType"));
        return;
      }

      try {
        // Read file content
        const fileContent = await file.text();
        let agentInfo;

        try {
          agentInfo = JSON.parse(fileContent);
        } catch (parseError) {
          message.error(t("businessLogic.config.error.invalidFileType"));
          return;
        }

        // Check if it's ExportAndImportDataFormat (has agent_id and agent_info)
        if (agentInfo.agent_id && agentInfo.agent_info && typeof agentInfo.agent_info === "object") {
          // Use AgentImportWizard for full agent import with configuration
          const importData: ImportAgentData = {
            agent_id: agentInfo.agent_id,
            agent_info: agentInfo.agent_info,
            mcp_info: agentInfo.mcp_info || [],
          };
          setImportWizardData(importData);
          setImportWizardVisible(true);
          return;
        }

        // Fallback to legacy import logic for other formats
        const normalizeValue = (value?: string | null) =>
          typeof value === "string" ? value.trim() : "";

        const extractImportedAgents = (data: any): any[] => {
          if (!data) {
            return [];
          }

          if (Array.isArray(data)) {
            return data;
          }

          if (data.agent_info && typeof data.agent_info === "object") {
            return Object.values(data.agent_info).filter(
              (item) => item && typeof item === "object"
            );
          }

          if (data.agentInfo && typeof data.agentInfo === "object") {
            return Object.values(data.agentInfo).filter(
              (item) => item && typeof item === "object"
            );
          }

          return [data];
        };

        const importedAgents = extractImportedAgents(agentInfo);
        const agentList = Array.isArray(subAgentList) ? subAgentList : [];

        const existingNames = new Set(
          agentList
            .map((agent) => normalizeValue(agent?.name))
            .filter((name) => !!name)
        );
        const existingDisplayNames = new Set(
          agentList
            .map((agent) => normalizeValue(agent?.display_name))
            .filter((name) => !!name)
        );

        const duplicateNames = Array.from(
          new Set(
            importedAgents
              .map((agent) => normalizeValue(agent?.name))
              .filter(
                (name) => name && existingNames.has(name)
              ) as string[]
          )
        );
        const duplicateDisplayNames = Array.from(
          new Set(
            importedAgents
              .map((agent) =>
                normalizeValue(agent?.display_name ?? agent?.displayName)
              )
              .filter(
                (displayName) =>
                  displayName && existingDisplayNames.has(displayName)
              ) as string[]
          )
        );

        const hasNameConflict = duplicateNames.length > 0;
        const hasDisplayNameConflict = duplicateDisplayNames.length > 0;

        if (hasNameConflict || hasDisplayNameConflict) {
          setPendingImportData({
            agentInfo,
          });
        } else {
          await runAgentImport(agentInfo);
        }
      } catch (error) {
        log.error(t("agentConfig.agents.importFailed"), error);
        message.error(t("businessLogic.config.error.agentImportFailed"));
      }
    };

    fileInput.click();
  };

  // Handle import completion from wizard
  const handleImportComplete = () => {
    refreshAgentList(t, false);
    setImportWizardVisible(false);
    setImportWizardData(null);
  };

  const handleConfirmedDuplicateImport = useCallback(async () => {
    if (!pendingImportData) {
      return;
    }
    setImportingAction("regenerate");
    const success = await runAgentImport(pendingImportData.agentInfo);
    if (success) {
      setPendingImportData(null);
    }
    setImportingAction(null);
  }, [pendingImportData, runAgentImport, t]);

  const handleForceDuplicateImport = useCallback(async () => {
    if (!pendingImportData) {
      return;
    }
    setImportingAction("force");
    const success = await runAgentImport(pendingImportData.agentInfo, {
      forceImport: true,
    });
    if (success) {
      setPendingImportData(null);
    }
    setImportingAction(null);
  }, [pendingImportData, runAgentImport, t]);

  // Handle confirmed deletion
  const handleConfirmDelete = async (agent: Agent) => {
    try {
      const result = await deleteAgent(Number(agent.id));
      if (result.success) {
        message.success(
          t("businessLogic.config.error.agentDeleteSuccess", {
            name: agent.name,
          })
        );
        // If currently editing the deleted agent, reset to initial clean state and avoid confirm modal on next switch
        const deletedId = Number(agent.id);
        const currentEditingId =
          (isEditingAgent && editingAgent ? Number(editingAgent.id) : null) ??
          null;
        if (currentEditingId === deletedId) {
          // Clear editing/creation states
          setIsEditingAgent(false);
          setEditingAgent(null);
          setIsCreatingNewAgent(false);
          setMainAgentId(null);
          // Clear form/content states
          setBusinessLogic("");
          setDutyContent?.("");
          setConstraintContent?.("");
          setFewShotsContent?.("");
          setAgentName?.("");
          setAgentDescription?.("");
          setAgentDisplayName?.("");
          setSelectedTools([]);
          setEnabledToolIds([]);
          setEnabledAgentIds([]);
          // Reset baseline/dirty and bypass next unsaved check
          baselineRef.current = null;
          setHasUnsavedChanges(false);
          onUnsavedChange?.(false);
          skipUnsavedCheckRef.current = true;
          setTimeout(() => {
            skipUnsavedCheckRef.current = false;
          }, 0);
          onEditingStateChange?.(false, null);
        } else {
          // If deleting another agent that is in enabledAgentIds, remove it and update baseline
          // to avoid triggering false unsaved changes indicator
          const deletedId = Number(agent.id);
          if (enabledAgentIds.includes(deletedId)) {
            const updatedEnabledAgentIds = enabledAgentIds.filter(
              (id) => id !== deletedId
            );
            setEnabledAgentIds(updatedEnabledAgentIds);
            // Update baseline to reflect this change so it doesn't trigger unsaved changes
            if (baselineRef.current) {
              baselineRef.current = {
                ...baselineRef.current,
                enabledAgentIds: updatedEnabledAgentIds.sort((a, b) => a - b),
              };
            }
          }
        }
        // Refresh agent list without clearing tools to avoid triggering false unsaved changes indicator
        refreshAgentList(t, false);
      } else {
        message.error(
          result.message || t("businessLogic.config.error.agentDeleteFailed")
        );
      }
    } catch (error) {
      log.error(t("agentConfig.agents.deleteFailed"), error);
      message.error(t("businessLogic.config.error.agentDeleteFailed"));
    }
  };

  // Handle export agent from list
  const handleExportAgentFromList = async (agent: Agent) => {
    try {
      const result = await exportAgent(Number(agent.id));
      if (result.success && result.data) {
        // Create a blob and download the file
        const blob = new Blob([JSON.stringify(result.data, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${agent.name || "agent"}.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        message.success(t("businessLogic.config.message.agentExportSuccess"));
      } else {
        message.error(
          result.message || t("businessLogic.config.error.agentExportFailed")
        );
      }
    } catch (error) {
      log.error("Failed to export agent:", error);
      message.error(t("businessLogic.config.error.agentExportFailed"));
    }
  };

  // Handle copy agent from list
  const handleCopyAgentFromList = async (agent: Agent) => {
    try {
      // Fetch source agent detail before duplicating
      const detailResult = await searchAgentInfo(Number(agent.id));
      if (!detailResult.success || !detailResult.data) {
        message.error(detailResult.message);
        return;
      }
      const detail = detailResult.data;

      // Prepare copy names
      const copyName = `${detail.name || "agent"}_copy`;
      const copyDisplayName = `${
        detail.display_name || t("agentConfig.agents.defaultDisplayName")
      }${t("agent.copySuffix")}`;

      // Gather tool and sub-agent identifiers from the source agent
      const tools = Array.isArray(detail.tools) ? detail.tools : [];
      const unavailableTools = tools.filter(
        (tool: any) => tool && tool.is_available === false
      );
      const unavailableToolNames = unavailableTools
        .map(
          (tool: any) =>
            tool?.display_name || tool?.name || tool?.tool_name || ""
        )
        .filter((name: string) => Boolean(name));

      const enabledToolIds = tools
        .filter((tool: any) => tool && tool.is_available !== false)
        .map((tool: any) => Number(tool.id))
        .filter((id: number) => Number.isFinite(id));
      const subAgentIds = (Array.isArray(detail.sub_agent_id_list)
        ? detail.sub_agent_id_list
        : []
      )
        .map((id: any) => Number(id))
        .filter((id: number) => Number.isFinite(id));

      // Create a new agent using the source agent fields
      const createResult = await updateAgent(
        undefined,
        copyName,
        detail.description,
        detail.model,
        detail.max_step,
        detail.provide_run_summary,
        detail.enabled,
        detail.business_description,
        detail.duty_prompt,
        detail.constraint_prompt,
        detail.few_shots_prompt,
        copyDisplayName,
        detail.model_id ?? undefined,
        detail.business_logic_model_name ?? undefined,
        detail.business_logic_model_id ?? undefined,
        enabledToolIds,
        subAgentIds
      );
      if (!createResult.success || !createResult.data?.agent_id) {
        message.error(
          createResult.message ||
            t("agentConfig.agents.copyFailed")
        );
        return;
      }
      const newAgentId = Number(createResult.data.agent_id);
      const copiedAgentFallback: Agent = {
        ...detail,
        id: String(newAgentId),
        name: copyName,
        display_name: copyDisplayName,
        sub_agent_id_list: subAgentIds,
      };

      // Copy tool configuration to the new agent
      for (const tool of tools) {
        if (!tool || tool.is_available === false) {
          continue;
        }
        const params =
          tool.initParams?.reduce((acc: Record<string, any>, param: any) => {
            acc[param.name] = param.value;
            return acc;
          }, {}) || {};
        try {
          await updateToolConfig(Number(tool.id), newAgentId, params, true);
        } catch (error) {
          log.error("Failed to copy tool configuration while duplicating agent:", error);
          message.error(
            t("agentConfig.agents.copyFailed")
          );
          return;
        }
      }

      // Refresh UI state and notify user about copy result
      await refreshAgentList(t, false);
      message.success(t("agentConfig.agents.copySuccess"));
      if (unavailableTools.length > 0) {
        const names =
          unavailableToolNames.join(", ") ||
          unavailableTools
            .map((tool: any) => Number(tool?.id))
            .filter((id: number) => !Number.isNaN(id))
            .join(", ");
        message.warning(
          t("agentConfig.agents.copyUnavailableTools", {
            count: unavailableTools.length,
            names,
          })
        );
      }
      // Auto select the newly copied agent for editing
      await handleEditAgent(copiedAgentFallback, t);
    } catch (error) {
      log.error("Failed to copy agent:", error);
      message.error(t("agentConfig.agents.copyFailed"));
    }
  };

  const handleCopyAgentWithConfirm = (agent: Agent) => {
    confirm({
      title: t("agentConfig.agents.copyConfirmTitle"),
      content: t("agentConfig.agents.copyConfirmContent", {
        name: agent?.display_name || agent?.name || "",
      }),
      onOk: () => handleCopyAgentFromList(agent),
    });
  };

  // Handle delete agent from list
  const handleDeleteAgentFromList = (agent: Agent) => {
    confirm({
      title: t("businessLogic.config.modal.deleteTitle"),
      content: t("businessLogic.config.modal.deleteContent", {
        name: agent.name,
      }),
      onOk: () => handleConfirmDelete(agent),
    });
  };

  // Refresh tool list
  const handleToolsRefresh = useCallback(
    async (showSuccessMessage = true) => {
      if (onToolsRefresh) {
        // Before refreshing the tool list, synchronize the selected tools using search_info.
        const currentAgentId = (isEditingAgent && editingAgent
          ? Number(editingAgent.id)
          : mainAgentId
          ? Number(mainAgentId)
          : undefined) as number | undefined;
        if (currentAgentId) {
          await refreshAgentToolSelectionsFromServer(currentAgentId);
        }
        const refreshedTools = await onToolsRefresh(showSuccessMessage);
        if (refreshedTools) {
          shouldRefreshEnabledToolIds.current = true;
        }
        return refreshedTools;
      }
      return undefined;
    },
    [onToolsRefresh, isEditingAgent, editingAgent, mainAgentId, refreshAgentToolSelectionsFromServer]
  );

  // Handle view call relationship
  const handleViewCallRelationship = () => {
    const currentAgentId = getCurrentAgentId?.() ?? undefined;
    if (currentAgentId) {
      setCallRelationshipModalVisible(true);
    }
  };

  // Get button tooltip information
  const getLocalButtonTitle = () => {
    if (!businessLogic || businessLogic.trim() === "") {
      return t("businessLogic.config.message.businessDescriptionRequired");
    }
    if (!mainAgentModel) {
      return t("businessLogic.config.message.selectModelRequired");
    }
    if (
      !dutyContent?.trim() &&
      !constraintContent?.trim() &&
      !fewShotsContent?.trim()
    ) {
      return t("businessLogic.config.message.generatePromptFirst");
    }
    if (!agentName || agentName.trim() === "") {
      return t("businessLogic.config.message.completeAgentInfo");
    }
    return "";
  };

  // Check if agent can be saved
  const localCanSaveAgent = !!(
    businessLogic?.trim() &&
    agentName?.trim() &&
    mainAgentModel &&
    (dutyContent?.trim() ||
      constraintContent?.trim() ||
      fewShotsContent?.trim())
  );

  const isForceDuplicateDisabled =
    isImporting && importingAction === "regenerate";
  const isRegenerateDuplicateDisabled =
    isImporting && importingAction === "force";
  const isForceDuplicateLoading = isImporting && importingAction === "force";

  return (
    <TooltipProvider>
      <div className="h-full relative px-2">
        {/* Three-column layout using Ant Design Grid */}
        <Row
          gutter={[16, 16]}
          className="h-full"
          align="stretch"
          style={{ minHeight: 0 }}
        >
          {/* Left column: SubAgentPool */}
          <Col
            xs={24}
            sm={24}
            md={24}
            lg={24}
            xl={8}
            className="flex flex-col h-full"
            style={{ height: "100%", minHeight: 0 }}
          >
            <SubAgentPool
              onEditAgent={(agent) => handleEditAgent(agent, t)}
              onCreateNewAgent={() => confirmOrRun(handleCreateNewAgent)}
              onExitEditMode={handleExitEditMode}
              onImportAgent={() => handleImportAgent(t)}
              subAgentList={subAgentList}
              loadingAgents={loadingAgents}
              isImporting={isImporting}
              isGeneratingAgent={isGeneratingAgent}
              editingAgent={editingAgent}
              isCreatingNewAgent={isCreatingNewAgent}
              onCopyAgent={handleCopyAgentWithConfirm}
              onExportAgent={handleExportAgentFromList}
              onDeleteAgent={handleDeleteAgentFromList}
              unsavedAgentId={
                hasUnsavedChanges && isEditingAgent && editingAgent
                  ? Number(editingAgent.id)
                  : null
              }
            />
          </Col>

          {/* Middle column: Agent capability configuration */}
          <Col
            xs={24}
            sm={24}
            md={24}
            lg={24}
            xl={8}
            className="flex flex-col h-full"
            style={{ height: "100%", minHeight: 0 }}
          >
            {/* Header: Configure Agent Capabilities */}
            <div className="flex justify-between items-center mb-2">
              <div className="flex items-center">
                <div className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-500 text-white text-sm font-medium mr-2">
                  2
                </div>
                <h2 className="text-lg font-medium m-0">
                  {t("businessLogic.config.title")}
                </h2>
              </div>
            </div>

            {/* Content: Two sections */}
            <div className="flex-1 overflow-hidden border-t border-gray-200 pt-2">
              <div className="flex flex-col h-full gap-4">
                {/* Upper section: Collaborative Agent Display - fixed area */}
                <CollaborativeAgentDisplay
                  className="h-[128px] flex-shrink-0"
                  availableAgents={subAgentList}
                  selectedAgentIds={enabledAgentIds}
                  parentAgentId={
                    isEditingAgent && editingAgent
                      ? Number(editingAgent.id)
                      : isCreatingNewAgent && mainAgentId
                      ? Number(mainAgentId)
                      : undefined
                  }
                  onAgentIdsChange={handleUpdateEnabledAgentIds}
                  isEditingMode={isEditingAgent || isCreatingNewAgent}
                  isGeneratingAgent={isGeneratingAgent}
                />

                {/* Lower section: Tool Pool - flexible area */}
                <div className="flex-1 overflow-hidden">
                  <MemoizedToolPool
                    selectedTools={isLoadingTools ? [] : selectedTools}
                    onSelectTool={(tool, isSelected) => {
                      if (isLoadingTools) return;
                      const toolId = Number(tool.id);
                      if (isSelected) {
                        // Avoid duplicate tools
                        if (!selectedTools.some((t) => t.id === tool.id)) {
                          setSelectedTools([...selectedTools, tool]);
                        }
                        // Sync enabledToolIds, ensure no duplicates
                        setEnabledToolIds((prev) => {
                          if (prev.includes(toolId)) {
                            return prev;
                          }
                          return [...prev, toolId].sort((a, b) => a - b);
                        });
                      } else {
                        setSelectedTools(
                          selectedTools.filter((t) => t.id !== tool.id)
                        );
                        // Sync enabledToolIds
                        setEnabledToolIds((prev) =>
                          prev.filter((id) => id !== toolId)
                        );
                      }
                    }}
                    tools={tools}
                    loadingTools={isLoadingTools}
                    mainAgentId={
                      isEditingAgent && editingAgent
                        ? editingAgent.id
                        : mainAgentId
                    }
                    localIsGenerating={isGeneratingAgent}
                    onToolsRefresh={handleToolsRefresh}
                    isEditingMode={isEditingAgent || isCreatingNewAgent}
                    isGeneratingAgent={isGeneratingAgent}
                    isEmbeddingConfigured={isEmbeddingConfigured}
                    agentUnavailableReasons={agentUnavailableReasons}
                    onToolConfigSave={handleToolConfigDraftSave}
                    toolConfigDrafts={toolConfigDrafts}
                  />
                </div>
              </div>
            </div>
          </Col>

          {/* Right column: System Prompt Display */}
          <Col
            xs={24}
            sm={24}
            md={24}
            lg={24}
            xl={8}
            className="flex flex-col h-full"
            style={{ height: "100%", minHeight: "400px" }}
          >
            <PromptManager
              onDebug={onDebug ? () => confirmOrRun(() => onDebug()) : () => {}}
              agentId={
                getCurrentAgentId
                  ? getCurrentAgentId()
                  : isEditingAgent && editingAgent
                  ? Number(editingAgent.id)
                  : isCreatingNewAgent && mainAgentId
                  ? Number(mainAgentId)
                  : undefined
              }
              businessLogic={businessLogic}
              businessLogicError={businessLogicError}
              dutyContent={dutyContent}
              constraintContent={constraintContent}
              fewShotsContent={fewShotsContent}
              onDutyContentChange={setDutyContent}
              onConstraintContentChange={setConstraintContent}
              onFewShotsContentChange={setFewShotsContent}
              agentName={agentName}
              agentDescription={agentDescription}
              onAgentNameChange={setAgentName}
              onAgentDescriptionChange={setAgentDescription}
              agentDisplayName={agentDisplayName}
              onAgentDisplayNameChange={setAgentDisplayName}
              agentAuthor={agentAuthor}
              onAgentAuthorChange={setAgentAuthor}
              isEditingMode={isEditingAgent || isCreatingNewAgent}
              mainAgentModel={mainAgentModel ?? undefined}
              mainAgentModelId={mainAgentModelId}
              mainAgentMaxStep={mainAgentMaxStep}
              onModelChange={(value: string, modelId?: number) =>
                handleModelChange(value, modelId)
              }
              onMaxStepChange={handleMaxStepChange}
              onBusinessLogicChange={(value: string) => setBusinessLogic(value)}
              onBusinessLogicModelChange={handleBusinessLogicModelChange}
              businessLogicModel={businessLogicModel}
              businessLogicModelId={businessLogicModelId}
              onGenerateAgent={onGenerateAgent || (() => {})}
              onSaveAgent={handleSaveAgent}
              isGeneratingAgent={isGeneratingAgent}
              isCreatingNewAgent={isCreatingNewAgent}
              canSaveAgent={localCanSaveAgent}
              getButtonTitle={getLocalButtonTitle}
              editingAgent={editingAgentFromParent || editingAgent}
              onViewCallRelationship={handleViewCallRelationship}
            />
          </Col>
        </Row>


        {/* Save confirmation modal for unsaved changes (debug/navigation hooks) */}
        <SaveConfirmModal
          open={isSaveConfirmOpen}
          onCancel={async () => {
            if (confirmContext === "exitCreate") {
              // Discard draft and return to initial state
              await handleCancelCreating();
              setIsSaveConfirmOpen(false);
            } else {
              // Discard while switching/editing: reload backend state of current agent
              await reloadCurrentAgentData();
              setHasUnsavedChanges(false);
              onUnsavedChange?.(false);
              setIsSaveConfirmOpen(false);
              const action = pendingAction;
              setPendingAction(null);
              if (action) {
                skipUnsavedCheckRef.current = true;
                setTimeout(async () => {
                  try {
                    await Promise.resolve(action());
                  } finally {
                    skipUnsavedCheckRef.current = false;
                  }
                }, 0);
              }
            }
          }}
          onSave={async () => {
            // Save changes: for create mode or edit mode, reuse unified save path
            await saveAllChanges();
            setIsSaveConfirmOpen(false);
            const action = pendingAction;
            setPendingAction(null);
            if (action) {
              // Continue pending action after save (e.g., switch)
              skipUnsavedCheckRef.current = true;
              setTimeout(async () => {
                try {
                  await Promise.resolve(action());
                } finally {
                  skipUnsavedCheckRef.current = false;
                }
              }, 0);
            }
          }}
          onClose={() => {
            // Only close modal, don't execute discard logic
            setIsSaveConfirmOpen(false);
          }}
          canSave={localCanSaveAgent}
          invalidReason={
            localCanSaveAgent ? undefined : getLocalButtonTitle() || undefined
          }
        />
        {/* Duplicate import confirmation */}
        <Modal
          open={!!pendingImportData}
          title={
            <div className="flex items-center gap-2">
              <WarningFilled className="text-amber-500" />
              <span>{t("businessLogic.config.import.duplicateTitle")}</span>
            </div>
          }
          onCancel={() => {
            if (isImporting) {
              return;
            }
            setPendingImportData(null);
          }}
          maskClosable={!isImporting}
          closable={!isImporting}
          centered
          footer={
            <div className="flex justify-end gap-2">
              <Button
                onClick={() => !isImporting && setPendingImportData(null)}
                disabled={isImporting}
              >
                {t("businessLogic.config.import.duplicateCancel")}
              </Button>
              <Tooltip
                title={t("businessLogic.config.import.forceWarning")}
                placement="top"
              >
                <Button
                  type="default"
                  className={
                    isForceDuplicateDisabled
                      ? "bg-gray-200 border-gray-300 text-gray-500 cursor-not-allowed"
                      : isForceDuplicateLoading
                      ? "!bg-amber-200 !border-amber-500 !text-amber-800 cursor-default"
                      : "!border-amber-400 !text-amber-700 !bg-amber-50 hover:!bg-amber-200 hover:!border-amber-500 hover:!text-amber-800"
                  }
                  onClick={handleForceDuplicateImport}
                  loading={isForceDuplicateLoading}
                  disabled={isForceDuplicateDisabled}
                >
                  {t("businessLogic.config.import.forceButton")}
                </Button>
              </Tooltip>
              <Tooltip
                title={t("businessLogic.config.import.regenerateTooltip")}
                placement="top"
              >
                <Button
                  type="primary"
                  onClick={handleConfirmedDuplicateImport}
                  loading={isImporting && importingAction === "regenerate"}
                  disabled={isRegenerateDuplicateDisabled}
                >
                  {t("businessLogic.config.import.duplicateConfirm")}
                </Button>
              </Tooltip>
            </div>
          }
        >
          <p className="text-sm text-gray-700">
            {t("businessLogic.config.import.duplicateDescription")}
          </p>
        </Modal>
        {/* Agent Import Wizard */}
        <AgentImportWizard
          visible={importWizardVisible}
          onCancel={() => {
            setImportWizardVisible(false);
            setImportWizardData(null);
          }}
          initialData={importWizardData}
          onImportComplete={handleImportComplete}
          title={undefined} // Use default title
          agentDisplayName={
            importWizardData?.agent_info?.[String(importWizardData.agent_id)]?.display_name
          }
          agentDescription={
            importWizardData?.agent_info?.[String(importWizardData.agent_id)]?.description
          }
        />
        {/* Auto unselect knowledge_base_search notice when embedding not configured */}

        {/* Agent call relationship modal */}
        <AgentCallRelationshipModal
          visible={callRelationshipModalVisible}
          onClose={() => setCallRelationshipModalVisible(false)}
          agentId={
            (getCurrentAgentId
              ? getCurrentAgentId()
              : isEditingAgent && editingAgent
              ? Number(editingAgent.id)
              : isCreatingNewAgent && mainAgentId
              ? Number(mainAgentId)
              : undefined) ?? 0
          }
          agentName={
            editingAgentFromParent || editingAgent
              ? (editingAgentFromParent || editingAgent)?.display_name ||
                (editingAgentFromParent || editingAgent)?.name ||
                ""
              : ""
          }
        />
      </div>
    </TooltipProvider>
  );
}
