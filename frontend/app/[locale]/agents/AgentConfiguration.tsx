"use client";

import {
  useState,
  useEffect,
  useRef,
  forwardRef,
  useImperativeHandle,
  useCallback,
} from "react";
import { useTranslation } from "react-i18next";
import { Drawer, App } from "antd";
import {
  AGENT_SETUP_LAYOUT_DEFAULT,
  GENERATE_PROMPT_STREAM_TYPES,
} from "@/const/agentConfig";
import { SETUP_PAGE_CONTAINER, STANDARD_CARD } from "@/const/layoutConstants";
import { ModelOption } from "@/types/modelConfig";
import {
  LayoutConfig,
  AgentConfigDataResponse,
  AgentConfigCustomEvent,
  AgentRefreshEvent,
} from "@/types/agentConfig";
import {
  fetchTools,
  fetchAgentList,
  exportAgent,
  deleteAgent,
} from "@/services/agentConfigService";
import { generatePromptStream } from "@/services/promptService";
import { updateToolList } from "@/services/mcpService";
import log from "@/lib/logger";
import { configStore } from "@/lib/config";

import AgentSetupOrchestrator from "./components/AgentSetupOrchestrator";
import DebugConfig from "./components/DebugConfig";

import "../i18n";

// Layout Height Constant Configuration
const LAYOUT_CONFIG: LayoutConfig = AGENT_SETUP_LAYOUT_DEFAULT;

/**
 * Agent configuration main component
 * Provides a full-width interface for agent business logic configuration
 * Follows SETUP_PAGE_CONTAINER layout standards for consistent height and spacing
 */
export type AgentConfigHandle = {
  hasUnsavedChanges: () => boolean;
  saveAllChanges: () => Promise<void>;
  reloadCurrentAgentData: () => Promise<void>;
};

interface AgentConfigProps {
  canAccessProtectedData: boolean;
}

export default forwardRef<AgentConfigHandle, AgentConfigProps>(function AgentConfig(
  { canAccessProtectedData },
  ref
) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [businessLogic, setBusinessLogic] = useState("");
  const [selectedTools, setSelectedTools] = useState<any[]>([]);
  const [isDebugDrawerOpen, setIsDebugDrawerOpen] = useState(false);
  const [isCreatingNewAgent, setIsCreatingNewAgent] = useState(false);
  const [mainAgentModel, setMainAgentModel] = useState<string | null>(null);
  const [mainAgentModelId, setMainAgentModelId] = useState<number | null>(null);
  const [mainAgentMaxStep, setMainAgentMaxStep] = useState(5);
  const [businessLogicModel, setBusinessLogicModel] = useState<string | null>(
    null
  );
  const [businessLogicModelId, setBusinessLogicModelId] = useState<
    number | null
  >(null);
  const [tools, setTools] = useState<any[]>([]);
  const [mainAgentId, setMainAgentId] = useState<string | null>(null);
  const [subAgentList, setSubAgentList] = useState<any[]>([]);
  const [loadingAgents, setLoadingAgents] = useState(false);

  const [enabledAgentIds, setEnabledAgentIds] = useState<number[]>([]);

  const [isEditingAgent, setIsEditingAgent] = useState(false);
  const [editingAgent, setEditingAgent] = useState<any>(null);

  // Add state for three segmented content sections
  const [dutyContent, setDutyContent] = useState("");
  const [constraintContent, setConstraintContent] = useState("");
  const [fewShotsContent, setFewShotsContent] = useState("");

  // Add state for agent name and description
  const [agentName, setAgentName] = useState("");
  const [agentDescription, setAgentDescription] = useState("");
  const [agentDisplayName, setAgentDisplayName] = useState("");
  const [agentAuthor, setAgentAuthor] = useState("");

  // Add state for business logic and action buttons
  const [isGeneratingAgent, setIsGeneratingAgent] = useState(false);
  const [isEmbeddingConfigured, setIsEmbeddingConfigured] = useState(false);

  // Error state for business logic input
  const [businessLogicError, setBusinessLogicError] = useState(false);

  // Only auto scan once flag
  const hasAutoScanned = useRef(false);
  const unsavedRef = useRef(false);
  const saveHandlerRef = useRef<null | (() => Promise<void>)>(null);
  const reloadHandlerRef = useRef<null | (() => Promise<void>)>(null);

  useImperativeHandle(ref, () => ({
    hasUnsavedChanges: () => unsavedRef.current,
    saveAllChanges: async () => {
      if (saveHandlerRef.current) {
        await saveHandlerRef.current();
      }
    },
    reloadCurrentAgentData: async () => {
      if (reloadHandlerRef.current) {
        await reloadHandlerRef.current();
      }
    },
  }));

  // Handle generate agent
  const handleGenerateAgent = async (selectedModel?: ModelOption) => {
    if (!businessLogic || businessLogic.trim() === "") {
      setBusinessLogicError(true);
      message.warning(
        t("businessLogic.config.error.businessDescriptionRequired")
      );
      // Scroll to business logic input after a short delay to ensure it's visible
      setTimeout(() => {
        const businessLogicInput = document.querySelector(
          "[data-business-logic-input]"
        );
        if (businessLogicInput) {
          businessLogicInput.scrollIntoView({
            behavior: "smooth",
            block: "center",
          });
        }
      }, 100);
      return;
    }
    // Clear error when validation passes
    setBusinessLogicError(false);

    // In create mode, agent_id should be 0 (backend will handle this case)
    // In edit mode, use the current agent id
    const currentAgentId = getCurrentAgentId();
    const agentIdToUse = isCreatingNewAgent ? 0 : currentAgentId || 0;

    if (!isCreatingNewAgent && !currentAgentId) {
      message.error(t("businessLogic.config.error.noAgentId"));
      return;
    }

    setIsGeneratingAgent(true);
    try {
      const currentAgentName = agentName;
      const currentAgentDisplayName = agentDisplayName;

      // Extract tool IDs from selected tools (convert string IDs to numbers)
      // Always pass tool_ids array (empty array means no tools selected, undefined means use database)
      // In edit mode, we want to use current selection, so pass the array even if empty
      const toolIds = selectedTools.map((tool) => Number(tool.id));
      
      // Get sub-agent IDs from enabledAgentIds
      // Always pass sub_agent_ids array (empty array means no sub-agents selected, undefined means use database)
      // In edit mode, we want to use current selection, so pass the array even if empty
      const subAgentIds = [...enabledAgentIds];

      // Call backend API to generate agent prompt
      // Pass tool_ids and sub_agent_ids to use frontend selection instead of database query
      await generatePromptStream(
        {
          agent_id: agentIdToUse,
          task_description: businessLogic,
          model_id: selectedModel?.id?.toString() || "",
          tool_ids: toolIds,
          sub_agent_ids: subAgentIds,
        },
        (data) => {
          // Process streaming response data
          switch (data.type) {
            case GENERATE_PROMPT_STREAM_TYPES.DUTY:
              setDutyContent(data.content);
              break;
            case GENERATE_PROMPT_STREAM_TYPES.CONSTRAINT:
              setConstraintContent(data.content);
              break;
            case GENERATE_PROMPT_STREAM_TYPES.FEW_SHOTS:
              setFewShotsContent(data.content);
              break;
            case GENERATE_PROMPT_STREAM_TYPES.AGENT_VAR_NAME:
              // Only update if current agent name is empty
              if (!currentAgentName || currentAgentName.trim() === "") {
                setAgentName(data.content);
              }
              break;
            case GENERATE_PROMPT_STREAM_TYPES.AGENT_DESCRIPTION:
              setAgentDescription(data.content);
              break;
            case GENERATE_PROMPT_STREAM_TYPES.AGENT_DISPLAY_NAME:
              // Only update if current agent display name is empty
              if (
                !currentAgentDisplayName ||
                currentAgentDisplayName.trim() === ""
              ) {
                setAgentDisplayName(data.content);
              }
              break;
          }
        },
        (error) => {
          log.error("Generate prompt stream error:", error);
          message.error(t("businessLogic.config.message.generateError"));
        },
        () => {
          message.success(t("businessLogic.config.message.generateSuccess"));
        }
      );
    } catch (error) {
      log.error("Generate agent error:", error);
      message.error(t("businessLogic.config.message.generateError"));
    } finally {
      setIsGeneratingAgent(false);
    }
  };

  // Handle export agent
  const handleExportAgent = async () => {
    if (!editingAgent) {
      message.warning(t("agent.error.noAgentSelected"));
      return;
    }

    try {
      const result = await exportAgent(Number(editingAgent.id));
      if (result.success) {
        // Handle backend returned string or object
        let exportData = result.data;
        if (typeof exportData === "string") {
          try {
            exportData = JSON.parse(exportData);
          } catch (e) {
            // If parsing fails, it means it's already a string, export directly
          }
        }
        const blob = new Blob([JSON.stringify(exportData, null, 2)], {
          type: "application/json",
        });

        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${editingAgent.name}_config.json`;
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
      log.error(t("agentConfig.agents.exportFailed"), error);
      message.error(t("businessLogic.config.error.agentExportFailed"));
    }
  };

  // Handle delete agent
  const handleDeleteAgent = async () => {
    if (!editingAgent) {
      message.warning(t("agent.error.noAgentSelected"));
      return;
    }

    try {
      const result = await deleteAgent(Number(editingAgent.id));
      if (result.success) {
        message.success(
          t("businessLogic.config.message.agentDeleteSuccess", {
            name: editingAgent.name,
          })
        );
        // Reset editing state
        setIsEditingAgent(false);
        setEditingAgent(null);
        setBusinessLogic("");
        setDutyContent("");
        setConstraintContent("");
        setFewShotsContent("");
        setAgentName("");
        setAgentDescription("");
        // Notify AgentManagementConfig to refresh agent list
        window.dispatchEvent(
          new CustomEvent("refreshAgentList") as AgentRefreshEvent
        );
      } else {
        message.error(
          result.message || t("businessLogic.config.message.agentDeleteFailed")
        );
      }
    } catch (error) {
      log.error(t("agentConfig.agents.deleteFailed"), error);
      message.error(t("businessLogic.config.message.agentDeleteFailed"));
    }
  };

  // Load tools when page is loaded
  useEffect(() => {
    if (!canAccessProtectedData) {
      return;
    }
    // Check embedding configuration once when entering the page
    try {
      const modelConfig = configStore.getModelConfig();
      setIsEmbeddingConfigured(!!modelConfig?.embedding?.modelName);
    } catch (e) {
      setIsEmbeddingConfigured(false);
    }

    const loadTools = async () => {
      try {
        const result = await fetchTools();
        if (result.success) {
          setTools(result.data);
          // If the tool list is empty and auto scan hasn't been triggered, trigger scan once
          if (result.data.length === 0 && !hasAutoScanned.current) {
            hasAutoScanned.current = true;
            // Mark as auto scanned
            const scanResult = await updateToolList();
            if (!scanResult.success) {
              message.error(t("toolManagement.message.refreshFailed"));
              return;
            }
            message.success(t("toolManagement.message.refreshSuccess"));
            // After scan, fetch the tool list again
            const reFetch = await fetchTools();
            if (reFetch.success) {
              setTools(reFetch.data);
            }
          }
        } else {
          message.error(result.message);
        }
      } catch (error) {
        log.error(t("agent.error.loadTools"), error);
        message.error(t("agent.error.loadToolsRetry"));
      }
    };

    loadTools();
  }, [canAccessProtectedData, t]);

  // Get agent list
  const fetchAgents = async () => {
    setLoadingAgents(true);
    try {
      const result = await fetchAgentList();
      if (result.success) {
        // fetchAgentList now returns AgentBasicInfo[], so we just set the subAgentList
        setSubAgentList(result.data);
        // Clear other states since we don't have detailed info yet
        setMainAgentId(null);
        // No longer manually clear enabledAgentIds, completely rely on backend returned sub_agent_id_list
        setMainAgentModel(null);
        setMainAgentMaxStep(5);
        setBusinessLogic("");
        setDutyContent("");
        setConstraintContent("");
        setFewShotsContent("");
        setBusinessLogicError(false);
        // Clear agent name and description only when not in editing mode
        if (!isEditingAgent) {
          setAgentName("");
          setAgentDescription("");
          setAgentDisplayName("");
        }
      } else {
        message.error(result.message || t("agent.error.fetchAgentList"));
      }
    } catch (error) {
      log.error(t("agent.error.fetchAgentList"), error);
      message.error(t("agent.error.fetchAgentListRetry"));
    } finally {
      setLoadingAgents(false);
    }
  };

  // Get agent list when component is loaded
  useEffect(() => {
    if (!canAccessProtectedData) {
      return;
    }
    fetchAgents();
  }, [canAccessProtectedData]);

  // Use refs to store latest values to avoid recreating event listener
  const businessLogicRef = useRef(businessLogic);
  const dutyContentRef = useRef(dutyContent);
  const constraintContentRef = useRef(constraintContent);
  const fewShotsContentRef = useRef(fewShotsContent);

  // Update refs when values change
  useEffect(() => {
    businessLogicRef.current = businessLogic;
  }, [businessLogic]);
  useEffect(() => {
    dutyContentRef.current = dutyContent;
  }, [dutyContent]);
  useEffect(() => {
    constraintContentRef.current = constraintContent;
  }, [constraintContent]);
  useEffect(() => {
    fewShotsContentRef.current = fewShotsContent;
  }, [fewShotsContent]);

  // Memoize event handler to avoid recreating listener
  const handleGetAgentConfigData = useCallback(() => {
    // Check if there is system prompt content
    let hasSystemPrompt = false;

    // If any of the segmented prompts has content, consider it as having system prompt
    if (dutyContentRef.current && dutyContentRef.current.trim() !== "") {
      hasSystemPrompt = true;
    } else if (
      constraintContentRef.current &&
      constraintContentRef.current.trim() !== ""
    ) {
      hasSystemPrompt = true;
    } else if (
      fewShotsContentRef.current &&
      fewShotsContentRef.current.trim() !== ""
    ) {
      hasSystemPrompt = true;
    }

    // Send the current configuration data to the main page
    const eventData: AgentConfigDataResponse = {
      businessLogic: businessLogicRef.current,
      systemPrompt: hasSystemPrompt ? "has_content" : "",
    };

    window.dispatchEvent(
      new CustomEvent("agentConfigDataResponse", {
        detail: eventData,
      }) as AgentConfigCustomEvent
    );
  }, []); // Empty deps - handler uses refs for latest values

  // Add event listener to respond to the data request from the main page
  useEffect(() => {
    window.addEventListener("getAgentConfigData", handleGetAgentConfigData);

    return () => {
      window.removeEventListener(
        "getAgentConfigData",
        handleGetAgentConfigData
      );
    };
  }, [handleGetAgentConfigData]);

  const handleEditingStateChange = (isEditing: boolean, agent: any) => {
    setIsEditingAgent(isEditing);
    setEditingAgent(agent);

    // When starting to edit agent, set agent name and description to the right-side name description box
    if (isEditing && agent) {
      setAgentName(agent.name || "");
      setAgentDescription(agent.description || "");
      setAgentAuthor(agent.author || "");
      setBusinessLogicError(false);
    } else if (!isEditing) {
      // When stopping editing, clear name description box
      setAgentName("");
      setAgentDescription("");
      setAgentDisplayName("");
      setAgentAuthor("");
      setBusinessLogicError(false);
    }
  };

  const getCurrentAgentId = () => {
    // In edit mode, always use the currently editing agent's id
    if (isEditingAgent && editingAgent) {
      return parseInt(editingAgent.id);
    }
    // In create mode, the agent has not been persisted yet, so there should be no agent_id
    if (isCreatingNewAgent) {
      return undefined;
    }
    // Fallback to mainAgentId when not creating and not explicitly editing
    return mainAgentId ? parseInt(mainAgentId) : undefined;
  };

  // Handle exit creation mode - should clear cache
  const handleExitCreation = () => {
    setIsCreatingNewAgent(false);
    setBusinessLogic("");
    setDutyContent("");
    setConstraintContent("");
    setFewShotsContent("");
    setAgentName("");
    setAgentDescription("");
    setAgentAuthor("");
    setBusinessLogicError(false);
  };

  // Refresh tool list
  const handleToolsRefresh = async (showSuccessMessage = true) => {
    try {
      const result = await fetchTools();
      if (result.success) {
        setTools(result.data);
        // Only show success message if explicitly requested (e.g., manual refresh)
        // Don't show message when auto-refreshing after MCP tool add/delete
        if (showSuccessMessage) {
          message.success(t("agentConfig.tools.refreshSuccess"));
        }
        return result.data; // Return the updated tools list
      } else {
        message.error(t("agentConfig.tools.refreshFailed"));
        return null;
      }
    } catch (error) {
      log.error(t("agentConfig.tools.refreshFailedDebug"), error);
      message.error(t("agentConfig.tools.refreshFailed"));
      return null;
    }
  };

  return (
    <App>
      <div
        className="w-full mx-auto"
        style={{
          maxWidth: SETUP_PAGE_CONTAINER.MAX_WIDTH,
          padding: `0 ${SETUP_PAGE_CONTAINER.HORIZONTAL_PADDING}`,
        }}
      >
        <div
          className={STANDARD_CARD.BASE_CLASSES}
          style={{
            height: SETUP_PAGE_CONTAINER.MAIN_CONTENT_HEIGHT,
            ...STANDARD_CARD.CONTENT_SCROLL,
          }}
        >
          <div style={{ padding: STANDARD_CARD.PADDING, height: "100%" }}>
            <AgentSetupOrchestrator
              businessLogic={businessLogic}
              setBusinessLogic={(value) => {
                setBusinessLogic(value);
                // Clear error when user starts typing
                if (businessLogicError && value.trim() !== "") {
                  setBusinessLogicError(false);
                }
              }}
              businessLogicError={businessLogicError}
              selectedTools={selectedTools}
              setSelectedTools={setSelectedTools}
              isCreatingNewAgent={isCreatingNewAgent}
              setIsCreatingNewAgent={setIsCreatingNewAgent}
              mainAgentModel={mainAgentModel}
              setMainAgentModel={setMainAgentModel}
              mainAgentModelId={mainAgentModelId}
              setMainAgentModelId={setMainAgentModelId}
              mainAgentMaxStep={mainAgentMaxStep}
              setMainAgentMaxStep={setMainAgentMaxStep}
              businessLogicModel={businessLogicModel}
              setBusinessLogicModel={setBusinessLogicModel}
              businessLogicModelId={businessLogicModelId}
              setBusinessLogicModelId={setBusinessLogicModelId}
              tools={tools}
              subAgentList={subAgentList}
              loadingAgents={loadingAgents}
              mainAgentId={mainAgentId}
              setMainAgentId={setMainAgentId}
              setSubAgentList={setSubAgentList}
              enabledAgentIds={enabledAgentIds}
              setEnabledAgentIds={setEnabledAgentIds}
              onEditingStateChange={handleEditingStateChange}
              onToolsRefresh={handleToolsRefresh}
              dutyContent={dutyContent}
              setDutyContent={setDutyContent}
              constraintContent={constraintContent}
              setConstraintContent={setConstraintContent}
              fewShotsContent={fewShotsContent}
              setFewShotsContent={setFewShotsContent}
              agentName={agentName}
              setAgentName={setAgentName}
              agentDescription={agentDescription}
              setAgentDescription={setAgentDescription}
              agentDisplayName={agentDisplayName}
              setAgentDisplayName={setAgentDisplayName}
              agentAuthor={agentAuthor}
              setAgentAuthor={setAgentAuthor}
              isGeneratingAgent={isGeneratingAgent}
              // SystemPromptDisplay related props
              onDebug={() => {
                setIsDebugDrawerOpen(true);
              }}
              getCurrentAgentId={getCurrentAgentId}
              onGenerateAgent={handleGenerateAgent}
              onExportAgent={handleExportAgent}
              onDeleteAgent={handleDeleteAgent}
              editingAgent={editingAgent}
              onExitCreation={handleExitCreation}
              isEmbeddingConfigured={isEmbeddingConfigured}
              onUnsavedChange={(dirty) => {
                unsavedRef.current = dirty;
              }}
              registerSaveHandler={(handler) => {
                saveHandlerRef.current = handler;
              }}
              registerReloadHandler={(handler) => {
                reloadHandlerRef.current = handler;
              }}
            />
          </div>
        </div>
      </div>

      {/* Debug drawer */}
      <Drawer
        title={t("agent.debug.title")}
        placement="right"
        onClose={() => setIsDebugDrawerOpen(false)}
        open={isDebugDrawerOpen}
        width={LAYOUT_CONFIG.DRAWER_WIDTH}
        destroyOnClose={true}
        styles={{
          body: {
            padding: 0,
            height: "100%",
            overflow: "hidden",
          },
        }}
      >
        <div className="h-full">
          <DebugConfig agentId={getCurrentAgentId()} />
        </div>
      </Drawer>
    </App>
  );
});
