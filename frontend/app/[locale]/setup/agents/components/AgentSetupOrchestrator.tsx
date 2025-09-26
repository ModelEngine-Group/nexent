"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { TFunction } from "i18next";

import { App, Modal, Typography, Button } from "antd";
import { WarningFilled } from "@ant-design/icons";

import { TooltipProvider } from "@/components/ui/tooltip";
import {
  getCreatingSubAgentId,
  fetchAgentList,
  updateAgent,
  importAgent,
  deleteAgent,
  searchAgentInfo,
  searchToolConfig,
  updateToolConfig,
} from "@/services/agentConfigService";
import { Agent, AgentSetupOrchestratorProps } from "@/types/agentConfig";
import log from "@/lib/logger";

import SubAgentPool from "./agent/SubAgentPool";
import CollaborativeAgentDisplay from "./agent/CollaborativeAgentDisplay";
import { MemoizedToolPool } from "./tool/ToolPool";
import PromptManager from "./PromptManager";

/**
 * Agent Setup Orchestrator - Main coordination component for agent setup workflow
 */
export default function AgentSetupOrchestrator({
  businessLogic,
  setBusinessLogic,
  selectedTools,
  setSelectedTools,
  isCreatingNewAgent,
  setIsCreatingNewAgent,
  mainAgentModel,
  setMainAgentModel,
  mainAgentMaxStep,
  setMainAgentMaxStep,
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
}: AgentSetupOrchestratorProps) {
  const [enabledToolIds, setEnabledToolIds] = useState<number[]>([]);
  const [isLoadingTools, setIsLoadingTools] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  // Use generation state passed from parent component, not local state

  // Delete confirmation popup status
  const [isDeleteConfirmOpen, setIsDeleteConfirmOpen] = useState(false);
  const [agentToDelete, setAgentToDelete] = useState<Agent | null>(null);

  // Embedding auto-unselect notice modal
  const [isEmbeddingAutoUnsetOpen, setIsEmbeddingAutoUnsetOpen] =
    useState(false);
  const lastProcessedAgentIdForEmbedding = useRef<number | null>(null);

  // Edit agent related status
  const [isEditingAgent, setIsEditingAgent] = useState(false);
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);

  // Add a flag to track if it has been initialized to avoid duplicate calls
  const hasInitialized = useRef(false);

  const { t } = useTranslation("common");
  const { message } = App.useApp();

  // Common refresh agent list function, moved to the front to avoid hoisting issues
  const refreshAgentList = async (t: TFunction) => {
    setIsLoadingTools(true);
    // Clear the tool selection status when loading starts
    setSelectedTools([]);
    setEnabledToolIds([]);

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
      setIsLoadingTools(false);
    }
  };

  // Function to directly update enabledAgentIds
  const handleUpdateEnabledAgentIds = (newEnabledAgentIds: number[]) => {
    setEnabledAgentIds(newEnabledAgentIds);
  };

  const fetchSubAgentIdAndEnableToolList = async (t: TFunction) => {
    setIsLoadingTools(false);

    try {
      const result = await getCreatingSubAgentId();
      if (result.success && result.data) {
        const {
          agentId,
          name,
          displayName,
          description,
          enabledToolIds,
          modelName,
          maxSteps,
          businessDescription,
          dutyPrompt,
          constraintPrompt,
          fewShotsPrompt,
          sub_agent_id_list,
        } = result.data;

        // Update the main agent ID
        setMainAgentId(agentId);
        // Update the main agent name
        setAgentName?.(name);
        // Update the main agent display name
        setAgentDisplayName?.(displayName);
        // Update the main agent description
        setAgentDescription?.(description);
        // Update the enabled tool ID list
        setEnabledToolIds(enabledToolIds);
        // Update the enabled agent ID list from sub_agent_id_list
        if (sub_agent_id_list && sub_agent_id_list.length > 0) {
          setEnabledAgentIds(sub_agent_id_list.map((id: any) => Number(id)));
        } else {
          setEnabledAgentIds([]);
        }
        // Update the model
        setMainAgentModel(modelName);
        // Update the maximum number of steps
        if (maxSteps) {
          setMainAgentMaxStep(maxSteps);
        }
        // Update the business description
        if (businessDescription) {
          setBusinessLogic(businessDescription);
        }
        // Update the duty prompt
        if (setDutyContent) {
          setDutyContent(dutyPrompt || "");
        }
        // Update the constraint prompt
        if (setConstraintContent) {
          setConstraintContent(constraintPrompt || "");
        }
        // Update the few shots prompt
        if (setFewShotsContent) {
          setFewShotsContent(fewShotsPrompt || "");
        }
      } else {
        message.error(
          result.message || t("businessLogic.config.error.agentIdFailed")
        );
      }
    } catch (error) {
      log.error("Failed to create new Agent:", error);
      message.error(t("businessLogic.config.error.agentIdFailed"));
    } finally {
      setIsLoadingTools(false);
    }
  };

  // Listen for changes in the creation of a new Agent
  useEffect(() => {
    if (isCreatingNewAgent) {
      if (!isEditingAgent) {
        // Only clear and get new Agent configuration in creating mode
        setBusinessLogic("");
        setMainAgentModel(null); // Clear model selection when creating new agent
        fetchSubAgentIdAndEnableToolList(t);
      } else {
        // In edit mode, data is loaded in handleEditAgent, here validate the form
      }
    } else {
      // When exiting the creation of a new Agent, reset the main Agent configuration
      // Only refresh list when exiting creation mode in non-editing mode to avoid flicker when exiting editing mode
      if (!isEditingAgent && hasInitialized.current) {
        setBusinessLogic("");
        setMainAgentModel(null);
        setMainAgentMaxStep(5);
        // Delay refreshing agent list to avoid jumping
        setTimeout(() => {
          refreshAgentList(t);
        }, 200);
      }
      // Sign that has been initialized
      hasInitialized.current = true;
    }
  }, [isCreatingNewAgent, isEditingAgent]);

  // Listen for changes in the tool status, update the selected tool
  useEffect(() => {
    if (!tools || !enabledToolIds || isLoadingTools) return;

    const enabledTools = tools.filter((tool) =>
      enabledToolIds.includes(Number(tool.id))
    );

    setSelectedTools(enabledTools);
  }, [tools, enabledToolIds, isLoadingTools]);

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
        setIsEmbeddingAutoUnsetOpen(true);
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

  // Handle the creation of a new Agent
  const handleCreateNewAgent = async () => {
    // Set to create mode
    setIsEditingAgent(false);
    setEditingAgent(null);
    setIsCreatingNewAgent(true);
    // Note: Don't clear content here - let the parent component's useEffect handle restoration
    // The parent component will restore cached content if available
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

      // Note: Content clearing is handled by onExitCreation above
      // Delay clearing tool and collaborative agent selection to avoid jumping
      setTimeout(() => {
        setSelectedTools([]);
        setEnabledToolIds([]);
        setEnabledAgentIds([]);
      }, 200);
    }, 100);
  };

  // Handle exit edit mode
  const handleExitEditMode = async () => {
    if (isCreatingNewAgent) {
      // If in creation mode, call cancel creation logic
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
    }
  };

  // Handle the creation of a new Agent
  const handleSaveNewAgent = async (
    name: string,
    description: string,
    model: string | null,
    max_step: number,
    business_description: string
  ) => {
    if (name.trim() && mainAgentId) {
      try {
        let result;

        if (isEditingAgent && editingAgent) {
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
            agentDisplayName
          );
        } else {
          result = await updateAgent(
            Number(mainAgentId),
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
            agentDisplayName
          );
        }

        if (result.success) {
          const actionText = isEditingAgent
            ? t("agent.action.modify")
            : t("agent.action.create");
          message.success(
            t("businessLogic.config.message.agentCreated", {
              name,
              action: actionText,
            })
          );

          setIsCreatingNewAgent(false);
          setIsEditingAgent(false);
          setEditingAgent(null);
          onEditingStateChange?.(false, null);

          setBusinessLogic("");
          setSelectedTools([]);
          setEnabledToolIds([]);
          // Clear right-side name description box
          setAgentName?.("");
          setAgentDescription?.("");
          // Clear segmented prompt content
          setDutyContent?.("");
          setConstraintContent?.("");
          setFewShotsContent?.("");

          refreshAgentList(t);
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
    try {
      // Call query interface to get complete Agent information
      const result = await searchAgentInfo(Number(agent.id));

      if (!result.success || !result.data) {
        message.error(
          result.message || t("businessLogic.config.error.agentDetailFailed")
        );
        return;
      }

      const agentDetail = result.data;

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

      // Notify external editing state change (use complete data)
      onEditingStateChange?.(true, agentDetail);

      // Load Agent data to interface
      setMainAgentModel(agentDetail.model);
      setMainAgentMaxStep(agentDetail.max_step);
      setBusinessLogic(agentDetail.business_description || "");

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
      if (agentDetail.tools && agentDetail.tools.length > 0) {
        setSelectedTools(agentDetail.tools);
        // Set enabled tool IDs
        const toolIds = agentDetail.tools.map((tool: any) => Number(tool.id));
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
  const handleModelChange = async (value: string) => {
    const targetAgentId =
      isEditingAgent && editingAgent ? editingAgent.id : mainAgentId;

    if (!targetAgentId) {
      message.error(t("businessLogic.config.error.noAgentId"));
      return;
    }
    setMainAgentModel(value);
  };

  // Handle the update of the maximum number of steps
  const handleMaxStepChange = async (value: number | null) => {
    const targetAgentId =
      isEditingAgent && editingAgent ? editingAgent.id : mainAgentId;

    if (!targetAgentId) {
      message.error(t("businessLogic.config.error.noAgentId"));
      return;
    }

    const newValue = value ?? 5;

    setMainAgentMaxStep(newValue);
  };

  // Handle importing agent
  const handleImportAgent = (t: TFunction) => {
    // Create a hidden file input element
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = ".json";
    fileInput.onchange = async (event) => {
      const file = (event.target as HTMLInputElement).files?.[0];
      if (!file) return;

      // Check file type
      if (!file.name.endsWith(".json")) {
        message.error(t("businessLogic.config.error.invalidFileType"));
        return;
      }

      setIsImporting(true);
      try {
        // Read file content
        const fileContent = await file.text();
        let agentInfo;

        try {
          agentInfo = JSON.parse(fileContent);
        } catch (parseError) {
          message.error(t("businessLogic.config.error.invalidFileType"));
          setIsImporting(false);
          return;
        }

        // Call import API
        const result = await importAgent(agentInfo);

        if (result.success) {
          message.success(t("businessLogic.config.error.agentImportSuccess"));
          // Refresh agent list
          refreshAgentList(t);
        } else {
          message.error(
            result.message || t("businessLogic.config.error.agentImportFailed")
          );
        }
      } catch (error) {
        log.error(t("agentConfig.agents.importFailed"), error);
        message.error(t("businessLogic.config.error.agentImportFailed"));
      } finally {
        setIsImporting(false);
      }
    };

    fileInput.click();
  };

  // Handle confirmed deletion
  const handleConfirmDelete = async (t: TFunction) => {
    if (!agentToDelete) return;

    try {
      const result = await deleteAgent(Number(agentToDelete.id));
      if (result.success) {
        message.success(
          t("businessLogic.config.error.agentDeleteSuccess", {
            name: agentToDelete.name,
          })
        );
        // Refresh agent list
        refreshAgentList(t);
      } else {
        message.error(
          result.message || t("businessLogic.config.error.agentDeleteFailed")
        );
      }
    } catch (error) {
      log.error(t("agentConfig.agents.deleteFailed"), error);
      message.error(t("businessLogic.config.error.agentDeleteFailed"));
    } finally {
      setIsDeleteConfirmOpen(false);
      setAgentToDelete(null);
    }
  };

  // Handle exit edit mode
  const handleExitEdit = () => {
    setIsEditingAgent(false);
    setEditingAgent(null);
    // Use the parent's exit creation handler to properly clear cache
    if (isCreatingNewAgent && onExitCreation) {
      onExitCreation();
    } else {
      setIsCreatingNewAgent(false);
    }
    setBusinessLogic("");
    setDutyContent("");
    setConstraintContent("");
    setFewShotsContent("");
    setAgentName?.("");
    setAgentDescription?.("");
    // Reset mainAgentId and enabledAgentIds
    setMainAgentId(null);
    setEnabledAgentIds([]);
    // Reset selected tools
    setSelectedTools([]);
    setEnabledToolIds([]);
    // Notify parent component about editing state change
    onEditingStateChange?.(false, null);
  };

  // Refresh tool list
  const handleToolsRefresh = useCallback(async () => {
    if (onToolsRefresh) {
      onToolsRefresh();
    }
  }, [onToolsRefresh]);

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

  return (
    <TooltipProvider>
      <div className="flex flex-col h-full gap-0 justify-between relative ml-2 mr-2">
        {/* Lower part: Agent pool + Agent capability configuration + System Prompt */}
        <div className="flex flex-col lg:flex-row gap-4 flex-1 min-h-0 max-w-full">
          {/* Left column: Always show SubAgentPool - Equal flex width */}
          <div className="w-full lg:w-auto lg:flex-1 h-full overflow-hidden">
            <SubAgentPool
              onEditAgent={(agent) => handleEditAgent(agent, t)}
              onCreateNewAgent={handleCreateNewAgent}
              onExitEditMode={handleExitEditMode}
              onImportAgent={() => handleImportAgent(t)}
              subAgentList={subAgentList}
              loadingAgents={loadingAgents}
              isImporting={isImporting}
              isGeneratingAgent={isGeneratingAgent}
              editingAgent={editingAgent}
              isCreatingNewAgent={isCreatingNewAgent}
            />
          </div>

          {/* Middle column: Agent capability configuration - Equal flex width */}
          <div className="w-full lg:w-auto lg:flex-1 h-full flex flex-col overflow-hidden">
            {/* Header: Configure Agent Capabilities */}
            <div className="flex justify-between items-center mb-2">
              <div className="flex items-center">
                <div className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-500 text-white text-sm font-medium mr-2">
                  2
                </div>
                <h2 className="text-lg font-medium">
                  {t("businessLogic.config.title")}
                </h2>
              </div>
            </div>

            {/* Content: ScrollArea with two sections */}
            <div className="flex-1 overflow-hidden border-t pt-2">
              <div className="flex flex-col h-full" style={{ gap: "16px" }}>
                {/* Upper section: Collaborative Agent Display - fixed area */}
                <CollaborativeAgentDisplay
                  className="h-[128px] lg:h-[128px]"
                  style={{ flexShrink: 0 }}
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
                      if (isSelected) {
                        setSelectedTools([...selectedTools, tool]);
                      } else {
                        setSelectedTools(
                          selectedTools.filter((t) => t.id !== tool.id)
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
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Right column: System Prompt Display - Equal flex width */}
          <div className="w-full lg:w-auto lg:flex-1 h-full overflow-hidden">
            <PromptManager
              onDebug={onDebug || (() => {})}
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
              isEditingMode={isEditingAgent || isCreatingNewAgent}
              mainAgentModel={mainAgentModel ?? undefined}
              mainAgentMaxStep={mainAgentMaxStep}
              onModelChange={(value: string) =>
                handleModelChange(value)
              }
              onMaxStepChange={handleMaxStepChange}
              onBusinessLogicChange={(value: string) => setBusinessLogic(value)}
              onGenerateAgent={onGenerateAgent || (() => {})}
              onSaveAgent={handleSaveAgent}
              isGeneratingAgent={isGeneratingAgent}
              isCreatingNewAgent={isCreatingNewAgent}
              canSaveAgent={localCanSaveAgent}
              getButtonTitle={getLocalButtonTitle}
              onExportAgent={onExportAgent || (() => {})}
              onDeleteAgent={onDeleteAgent || (() => {})}
              onDeleteSuccess={handleExitEdit}
              editingAgent={editingAgentFromParent || editingAgent}
            />
          </div>
        </div>

        {/* Delete confirmation popup */}
        <Modal
          title={t("businessLogic.config.modal.deleteTitle")}
          open={isDeleteConfirmOpen}
          onCancel={() => setIsDeleteConfirmOpen(false)}
          centered
          footer={
            <div className="flex justify-end gap-2">
              <Button
                type="primary"
                danger
                onClick={() => handleConfirmDelete(t)}
              >
                {t("common.confirm")}
              </Button>
            </div>
          }
          width={400}
        >
          <div className="py-4">
            <Typography.Text>
              {t("businessLogic.config.modal.deleteContent", {
                name: agentToDelete?.name,
              })}
            </Typography.Text>
          </div>
        </Modal>
        {/* Auto unselect knowledge_base_search notice when embedding not configured */}
        <Modal
          title={t("embedding.agentToolAutoDeselectModal.title")}
          open={isEmbeddingAutoUnsetOpen}
          onCancel={() => setIsEmbeddingAutoUnsetOpen(false)}
          centered
          footer={
            <div className="flex justify-end mt-6 gap-4">
              <Button
                type="primary"
                onClick={() => setIsEmbeddingAutoUnsetOpen(false)}
              >
                {t("common.confirm")}
              </Button>
            </div>
          }
          width={520}
        >
          <div className="py-2">
            <div className="flex items-center">
              <WarningFilled
                className="text-yellow-500 mt-1 mr-2"
                style={{ fontSize: "48px" }}
              />
              <div className="ml-3 mt-2">
                <div className="text-sm leading-6">
                  {t("embedding.agentToolAutoDeselectModal.content")}
                </div>
              </div>
            </div>
          </div>
        </Modal>
      </div>
    </TooltipProvider>
  );
}
