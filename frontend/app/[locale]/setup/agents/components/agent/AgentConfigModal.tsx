"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { Button, Modal, Spin, Input, Select, InputNumber } from "antd";
import {
  ExpandAltOutlined,
  SaveOutlined,
  LoadingOutlined,
  BugOutlined,
  UploadOutlined,
  DeleteOutlined,
} from "@ant-design/icons";

import log from "@/lib/logger";
import { ModelOption } from "@/types/modelConfig";
import { modelService } from "@/services/modelService";
import {
  checkAgentName,
  checkAgentDisplayName,
} from "@/services/agentConfigService";
import { NAME_CHECK_STATUS } from "@/const/agentConfig";

import { SimplePromptEditor } from "../PromptManager";

export interface AgentConfigModalProps {
  agentId?: number;
  dutyContent?: string;
  constraintContent?: string;
  fewShotsContent?: string;
  onDutyContentChange?: (content: string) => void;
  onConstraintContentChange?: (content: string) => void;
  onFewShotsContentChange?: (content: string) => void;
  agentName?: string;
  agentDescription?: string;
  onAgentNameChange?: (name: string) => void;
  onAgentDescriptionChange?: (description: string) => void;
  agentDisplayName?: string;
  onAgentDisplayNameChange?: (displayName: string) => void;
  isEditingMode?: boolean;
  mainAgentModel?: string;
  mainAgentModelId?: number | null;
  mainAgentMaxStep?: number;
  onModelChange?: (value: string, modelId?: number) => void;
  onMaxStepChange?: (value: number | null) => void;
  onSavePrompt?: () => void;
  onExpandCard?: (index: number) => void;
  isGeneratingAgent?: boolean;
  // Add new props for action buttons
  onDebug?: () => void;
  onExportAgent?: () => void;
  onDeleteAgent?: () => void;
  onDeleteSuccess?: () => void; // New prop for handling delete success
  onSaveAgent?: () => void;
  isCreatingNewAgent?: boolean;
  editingAgent?: any;
  canSaveAgent?: boolean;
  getButtonTitle?: () => string;
}

export default function AgentConfigModal({
  agentId,
  dutyContent = "",
  constraintContent = "",
  fewShotsContent = "",
  onDutyContentChange,
  onConstraintContentChange,
  onFewShotsContentChange,
  agentName = "",
  agentDescription = "",
  onAgentNameChange,
  onAgentDescriptionChange,
  agentDisplayName = "",
  onAgentDisplayNameChange,
  isEditingMode = false,
  mainAgentModel = "",
  mainAgentModelId = null,
  mainAgentMaxStep = 5,
  onModelChange,
  onMaxStepChange,
  onExpandCard,
  isGeneratingAgent = false,
  // Add new props for action buttons
  onDebug,
  onExportAgent,
  onDeleteAgent,
  onDeleteSuccess,
  onSaveAgent,
  isCreatingNewAgent = false,
  editingAgent,
  canSaveAgent = false,
  getButtonTitle,
}: AgentConfigModalProps) {
  const { t } = useTranslation("common");

  // Add local state to track content of three sections
  const [localDutyContent, setLocalDutyContent] = useState(dutyContent || "");
  const [localConstraintContent, setLocalConstraintContent] = useState(
    constraintContent || ""
  );
  const [localFewShotsContent, setLocalFewShotsContent] = useState(
    fewShotsContent || ""
  );

  // Add segmented state management
  const [activeSegment, setActiveSegment] = useState<string>("agent-info");

  // Add state for delete confirmation modal
  const [isDeleteModalVisible, setIsDeleteModalVisible] = useState(false);

  // Add state for agent name validation error
  const [agentNameError, setAgentNameError] = useState<string>("");
  // Add state for agent name status check
  const [agentNameStatus, setAgentNameStatus] = useState<string>("available");
  // Add state to track if user is actively typing agent name
  const [isUserTyping, setIsUserTyping] = useState(false);

  // Add state for agent display name validation error
  const [agentDisplayNameError, setAgentDisplayNameError] =
    useState<string>("");
  // Add state for agent display name status check
  const [agentDisplayNameStatus, setAgentDisplayNameStatus] =
    useState<string>("available");
  // Add state to track if user is actively typing agent display name
  const [isUserTypingDisplayName, setIsUserTypingDisplayName] = useState(false);

  // Add state for LLM models
  const [llmModels, setLlmModels] = useState<ModelOption[]>([]);
  // Local fallback for selected main model display name (used when parent has not yet propagated)
  const [localMainAgentModel, setLocalMainAgentModel] = useState<string>("");
  // Track if default model has been initialized
  const hasInitializedDefaultModel = useRef(false);

  // Load LLM models on component mount
  useEffect(() => {
    const loadLLMModels = async () => {
      try {
        const models = await modelService.getLLMModels();
        setLlmModels(models);
      } catch (error) {
        log.error("Failed to load LLM models:", error);
        setLlmModels([]);
      } finally {
      }
    };

    loadLLMModels();
  }, []);

  // Reset initialization flag when switching modes (editing existing vs creating new)
  useEffect(() => {
    if (isCreatingNewAgent) {
      // Reset flag when entering "create new agent" mode
      hasInitializedDefaultModel.current = false;
      // Clear local model state to force re-initialization from localStorage
      setLocalMainAgentModel("");
    }
  }, [isCreatingNewAgent]);

  // Reset local model state when switching to a different agent
  // Track the previous agentId to detect when it changes
  const prevAgentIdRef = useRef<number | undefined>(undefined);
  
  useEffect(() => {
    // Detect agent switch by comparing current and previous agentId
    // This includes: existing -> existing, existing -> undefined (create new), undefined -> existing
    const hasAgentChanged = agentId !== prevAgentIdRef.current;
    
    if (hasAgentChanged && prevAgentIdRef.current !== undefined) {
      // When switching from one agent to another (or from agent to "create new"),
      // clear local state and wait for parent to provide the saved value or re-initialize
      log.info("[AgentConfigModal] Agent changed from", prevAgentIdRef.current, "to", agentId, "- clearing local model state");
      setLocalMainAgentModel("");
    }
    
    // Always update the ref to track the current agentId
    prevAgentIdRef.current = agentId;
  }, [agentId]);

  // Default to globally configured model when creating a new agent (only once per creation session)
  useEffect(() => {
    if (!isCreatingNewAgent) return;
    if (!llmModels || llmModels.length === 0) return;
    // Only initialize once per creation session
    if (hasInitializedDefaultModel.current) return;

    try {
      // Read global default model from config store (written by quick setup)
      const storedModelConfig = localStorage.getItem("model");
      if (!storedModelConfig) return;
      
      const parsed = JSON.parse(storedModelConfig);
      const defaultDisplayName = parsed?.llm?.displayName || "";
      const defaultModelName = parsed?.llm?.modelName || "";

      let target = null as ModelOption | null;
      if (defaultDisplayName) {
        target = llmModels.find((m) => m.displayName === defaultDisplayName) || null;
      }
      if (!target && defaultModelName) {
        target = llmModels.find((m) => m.name === defaultModelName) || null;
      }
      if (!target) {
        target = llmModels[0] || null;
      }

      if (target) {
        log.info("[AgentConfigModal] Setting default model:", target.displayName);
        // Notify parent if provided
        onModelChange?.(target.displayName, target.id);
        // Also set local fallback immediately for UI before parent propagation
        setLocalMainAgentModel(target.displayName);
        hasInitializedDefaultModel.current = true;
      }
    } catch (e) {
      log.error("[AgentConfigModal] Error parsing model config:", e);
    }
  }, [isCreatingNewAgent, llmModels]);

  // Keep local fallback in sync when parent-controlled value arrives/changes
  useEffect(() => {
    // Always sync with parent when mainAgentModel changes
    if (mainAgentModel && mainAgentModel !== localMainAgentModel) {
      log.info("[AgentConfigModal] Syncing with parent model:", mainAgentModel);
      setLocalMainAgentModel(mainAgentModel);
    }
  }, [mainAgentModel]);

  // Agent name validation function
  const validateAgentName = useCallback(
    (name: string): string => {
      if (!name.trim()) {
        return t("agent.info.name.error.empty");
      }

      if (name.length > 50) {
        return t("agent.info.name.error.length");
      }

      // Can only contain underscores, English characters and numbers; follows variable naming conventions (cannot start with numbers)
      const namePattern = /^[a-zA-Z_][a-zA-Z0-9_]*$/;
      if (!namePattern.test(name)) {
        return t("agent.info.name.error.format");
      }

      return "";
    },
    [t]
  );

  // Handle agent name change with validation
  const handleAgentNameChange = useCallback(
    (name: string) => {
      const error = validateAgentName(name);
      setAgentNameError(error);
      onAgentNameChange?.(name);

      // Set user typing state to true when user actively changes the name
      setIsUserTyping(true);
    },
    [validateAgentName, onAgentNameChange]
  );

  // Agent display name validation function
  const validateAgentDisplayName = useCallback(
    (displayName: string): string => {
      if (!displayName.trim()) {
        return t("agent.info.displayName.error.empty");
      }
      if (displayName.length > 50) {
        return t("agent.info.displayName.error.length");
      }
      return "";
    },
    [t]
  );

  // Handle agent display name change with validation
  const handleAgentDisplayNameChange = useCallback(
    (displayName: string) => {
      const error = validateAgentDisplayName(displayName);
      setAgentDisplayNameError(error);
      onAgentDisplayNameChange?.(displayName);

      // Set user typing state to true when user actively changes the display name
      setIsUserTypingDisplayName(true);
    },
    [validateAgentDisplayName, onAgentDisplayNameChange]
  );

  // Check agent name existence - only when user is actively typing
  useEffect(() => {
    if (!agentName || agentNameError) {
      return;
    }

    const checkName = async () => {
      try {
        // Pass the current agent ID to exclude it from the check when editing
        const result = await checkAgentName(agentName, agentId);
        setAgentNameStatus(result.status);
      } catch (error) {
        log.error("check agent name failed:", error);
        setAgentNameStatus(NAME_CHECK_STATUS.CHECK_FAILED);
      }
    };

    const timer = setTimeout(() => {
      checkName();
    }, 300);

    return () => {
      clearTimeout(timer);
    };
  }, [isEditingMode, agentName, agentNameError, agentId, t]);

  // Reset user typing state after user stops typing
  useEffect(() => {
    if (!isUserTyping) return;

    const timer = setTimeout(() => {
      setIsUserTyping(false);
    }, 1000);

    return () => {
      clearTimeout(timer);
    };
  }, [isUserTyping, agentName]);

  // Clear name status when agent name is cleared or changed significantly
  useEffect(() => {
    if (!agentName || agentName.trim() === "") {
      setAgentNameStatus(NAME_CHECK_STATUS.AVAILABLE);
    }
  }, [agentName]);

  // Check agent display name existence - only when user is actively typing
  useEffect(() => {
    if (
      (!isEditingMode && !isCreatingNewAgent) ||
      !agentDisplayName ||
      agentDisplayNameError
    ) {
      return;
    }

    const checkDisplayName = async () => {
      try {
        // Pass the current agent ID to exclude it from the check when editing
        const result = await checkAgentDisplayName(agentDisplayName, agentId);
        setAgentDisplayNameStatus(result.status);
      } catch (error) {
        log.error("check agent display name failed:", error);
        setAgentDisplayNameStatus(NAME_CHECK_STATUS.CHECK_FAILED);
      }
    };

    const timer = setTimeout(() => {
      checkDisplayName();
    }, 300);

    return () => {
      clearTimeout(timer);
    };
  }, [isEditingMode, agentDisplayName, agentDisplayNameError, agentId, t]);

  // Reset user typing state for display name after user stops typing
  useEffect(() => {
    if (!isUserTypingDisplayName) return;

    const timer = setTimeout(() => {
      setIsUserTypingDisplayName(false);
    }, 1000);

    return () => {
      clearTimeout(timer);
    };
  }, [isUserTypingDisplayName, agentDisplayName]);

  // Clear display name status when agent display name is cleared or changed significantly
  useEffect(() => {
    if (!agentDisplayName || agentDisplayName.trim() === "") {
      setAgentDisplayNameStatus(NAME_CHECK_STATUS.AVAILABLE);
    }
  }, [agentDisplayName]);

  // Handle delete confirmation
  const handleDeleteConfirm = useCallback(() => {
    setIsDeleteModalVisible(false);
    // Execute the delete operation
    onDeleteAgent?.();
    // Call the success callback immediately after triggering delete
    // The actual success/failure will be handled by the parent component
    onDeleteSuccess?.();
  }, [onDeleteAgent, onDeleteSuccess]);

  // Handle delete button click
  const handleDeleteClick = useCallback(() => {
    setIsDeleteModalVisible(true);
  }, []);

  // Optimized click handlers using useCallback
  const handleSegmentClick = useCallback((segment: string) => {
    setActiveSegment(segment);
  }, []);

  // Set default active segment when entering edit mode
  useEffect(() => {
    if (isEditingMode) {
      setActiveSegment("agent-info");
    }
  }, [isEditingMode]);

  // Initialize local state with external content on mount or when content changes significantly
  useEffect(() => {
    setLocalDutyContent(dutyContent || "");
    setLocalConstraintContent(constraintContent || "");
    setLocalFewShotsContent(fewShotsContent || "");
  }, [dutyContent, constraintContent, fewShotsContent]);

  // Update local state when external content changes
  useEffect(() => {
    if (dutyContent !== undefined) {
      setLocalDutyContent(dutyContent);
    }
  }, [dutyContent]);

  useEffect(() => {
    if (constraintContent !== undefined) {
      setLocalConstraintContent(constraintContent);
    }
  }, [constraintContent]);

  useEffect(() => {
    if (fewShotsContent !== undefined) {
      setLocalFewShotsContent(fewShotsContent);
    }
  }, [fewShotsContent]);

  // Validate agent name when it changes externally
  useEffect(() => {
    if (agentName && isEditingMode) {
      const error = validateAgentName(agentName);
      setAgentNameError(error);
    } else {
      setAgentNameError("");
    }
  }, [agentName, isEditingMode, validateAgentName]);

  // Validate agent display name when it changes externally
  useEffect(() => {
    if (agentDisplayName && isEditingMode) {
      const error = validateAgentDisplayName(agentDisplayName);
      setAgentDisplayNameError(error);
    } else {
      setAgentDisplayNameError("");
    }
  }, [agentDisplayName, isEditingMode, validateAgentDisplayName]);

  // Calculate whether save buttons should be enabled
  const canActuallySave =
    canSaveAgent &&
    !agentNameError &&
    agentNameStatus !== NAME_CHECK_STATUS.EXISTS_IN_TENANT &&
    !agentDisplayNameError &&
    agentDisplayNameStatus !== NAME_CHECK_STATUS.EXISTS_IN_TENANT;

  // Render individual content sections
  const renderAgentInfo = () => (
    <div className="p-4 agent-info-content">
      {/* Agent Display Name */}
      <div className="mb-2">
        <label className="block text-sm font-medium text-gray-700 mb-1">
          {t("agent.displayName")}:
        </label>
        <Input
          value={agentDisplayName}
          onChange={(e) => {
            handleAgentDisplayNameChange(e.target.value);
          }}
          placeholder={t("agent.displayNamePlaceholder")}
          size="large"
          disabled={!isEditingMode}
          status={
            agentDisplayNameError ||
            agentDisplayNameStatus === NAME_CHECK_STATUS.EXISTS_IN_TENANT
              ? "error"
              : ""
          }
        />
        {agentDisplayNameError && (
          <p className="mt-1 text-sm text-red-600">{agentDisplayNameError}</p>
        )}
        {!agentDisplayNameError &&
          agentDisplayNameStatus === NAME_CHECK_STATUS.EXISTS_IN_TENANT && (
            <p className="mt-1 text-sm text-red-600">
              {t("agent.error.displayNameExists", {
                displayName: agentDisplayName,
              })}
            </p>
          )}
      </div>

      {/* Agent Name */}
      <div className="mb-2">
        <label className="block text-sm font-medium text-gray-700 mb-1">
          {t("agent.name")}:
        </label>
        <Input
          value={agentName}
          onChange={(e) => {
            handleAgentNameChange(e.target.value);
          }}
          placeholder={t("agent.namePlaceholder")}
          size="large"
          disabled={!isEditingMode}
          status={
            agentNameError ||
            agentNameStatus === NAME_CHECK_STATUS.EXISTS_IN_TENANT
              ? "error"
              : ""
          }
        />
        {agentNameError && (
          <p className="mt-1 text-sm text-red-600">{agentNameError}</p>
        )}
        {!agentNameError &&
          agentNameStatus === NAME_CHECK_STATUS.EXISTS_IN_TENANT && (
            <p className="mt-1 text-sm text-red-600">
              {t("agent.error.nameExists", { name: agentName })}
            </p>
          )}
      </div>

      {/* Model Selection */}
      <div className="mb-2">
        <label className="block text-sm font-medium text-gray-700 mb-1">
          {t("businessLogic.config.model")}:
        </label>
        <Select
          value={localMainAgentModel || mainAgentModel || undefined}
          onChange={(value) => {
            // Find the model by displayName to get the modelId
            const selectedModel = llmModels.find((m) => m.displayName === value);
            const modelId = selectedModel?.id;
            
            log.info("[AgentConfigModal] Model changed:", { value, modelId, isCreatingNewAgent, isEditingMode });
            
            // Update local state immediately for responsive UI
            setLocalMainAgentModel(value);
            // Notify parent to update shared state
            onModelChange?.(value, modelId);
          }}
          size="large"
          disabled={!isEditingMode}
          style={{ width: "100%" }}
          placeholder={t("businessLogic.config.modelPlaceholder")}
        >
          {llmModels.map((model) => (
            <Select.Option 
              key={model.id} 
              value={model.displayName}
              disabled={model.connect_status !== "available"}
            >
              <div className="flex items-center justify-between">
                <span>{model.displayName}</span>
              </div>
            </Select.Option>
          ))}
        </Select>
        {llmModels.length === 0 && (
          <p className="mt-1 text-sm text-gray-500">
            {t("businessLogic.config.error.noAvailableModels")}
          </p>
        )}
      </div>

      {/* Max Steps */}
      <div className="mb-2">
        <label className="block text-sm font-medium text-gray-700 mb-1">
          {t("businessLogic.config.maxSteps")}:
        </label>
        <InputNumber
          min={1}
          max={20}
          value={mainAgentMaxStep}
          onChange={(value) => onMaxStepChange?.(value)}
          size="large"
          disabled={!isEditingMode}
          style={{ width: "100%" }}
        />
      </div>

      {/* Agent Description */}
      <div className="mb-2">
        <label className="block text-sm font-medium text-gray-700 mb-1">
          {t("agent.description")}:
        </label>
        <Input.TextArea
          value={agentDescription}
          onChange={(e) => onAgentDescriptionChange?.(e.target.value)}
          placeholder={t("agent.descriptionPlaceholder")}
          rows={6}
          size="large"
          disabled={!isEditingMode}
          style={{
            minHeight: "150px",
            maxHeight: "200px",
            boxShadow: "none",
          }}
        />
      </div>
    </div>
  );

  const renderDutyContent = () => (
    <div className="p-1 h-full flex flex-col">
      <div className="flex-1 min-h-0">
        <SimplePromptEditor
          value={localDutyContent}
          onChange={(value: string) => {
            setLocalDutyContent(value);
            // Immediate update to parent component
            if (onDutyContentChange) {
              onDutyContentChange(value);
            }
          }}
        />
      </div>
    </div>
  );

  const renderConstraintContent = () => (
    <div className="p-1 h-full flex flex-col">
      <div className="flex-1 min-h-0">
        <SimplePromptEditor
          value={localConstraintContent}
          onChange={(value: string) => {
            setLocalConstraintContent(value);
            // Immediate update to parent component
            if (onConstraintContentChange) {
              onConstraintContentChange(value);
            }
          }}
        />
      </div>
    </div>
  );

  const renderFewShotsContent = () => (
    <div className="p-1 h-full flex flex-col">
      <div className="flex-1 min-h-0">
        <SimplePromptEditor
          value={localFewShotsContent}
          onChange={(value: string) => {
            setLocalFewShotsContent(value);
            // Immediate update to parent component
            if (onFewShotsContentChange) {
              onFewShotsContentChange(value);
            }
          }}
        />
      </div>
    </div>
  );

  return (
    <div
      className={`flex flex-col h-full relative mt-4 ${
        isEditingMode ? "editing-mode" : "viewing-mode"
      }`}
    >
      {/* Section Title */}
      <div className="flex justify-between items-center mb-2 flex-shrink-0">
        <div className="flex items-center">
          <h3 className="text-sm font-medium text-gray-700">
            {t("agent.detailContent.title")}
          </h3>
        </div>
      </div>

      {/* Segmented Control */}
      <div className="flex justify-center mb-4 flex-shrink-0">
        <div className="w-full max-w-4xl">
          <div className="flex bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
            <button
              onClick={handleSegmentClick.bind(null, "agent-info")}
              className={`flex-1 px-4 py-2 text-sm font-medium transition-colors text-sm segment-button ${
                activeSegment === "agent-info"
                  ? "bg-blue-500 text-white"
                  : "bg-white text-gray-700 hover:bg-gray-50"
              }`}
              style={{ fontSize: "14px" }}
              type="button"
            >
              {t("agent.info.title")}
            </button>
            <button
              onClick={handleSegmentClick.bind(null, "duty")}
              className={`flex-1 px-4 py-2 text-sm font-medium transition-colors relative text-sm segment-button ${
                activeSegment === "duty"
                  ? "bg-blue-500 text-white"
                  : "bg-white text-gray-700 hover:bg-gray-50"
              }`}
              style={{ fontSize: "14px" }}
              type="button"
            >
              {t("systemPrompt.card.duty.title")}
              {isGeneratingAgent && activeSegment === "duty" && (
                <LoadingOutlined className="ml-2 text-white" />
              )}
            </button>
            <button
              onClick={handleSegmentClick.bind(null, "constraint")}
              className={`flex-1 px-4 py-2 text-sm font-medium transition-colors relative text-sm segment-button ${
                activeSegment === "constraint"
                  ? "bg-blue-500 text-white"
                  : "bg-white text-gray-700 hover:bg-gray-50"
              }`}
              style={{ fontSize: "14px" }}
              type="button"
            >
              {t("systemPrompt.card.constraint.title")}
              {isGeneratingAgent && activeSegment === "constraint" && (
                <LoadingOutlined className="ml-2 text-white" />
              )}
            </button>
            <button
              onClick={handleSegmentClick.bind(null, "few-shots")}
              className={`flex-1 px-4 py-2 text-sm font-medium transition-colors relative text-sm segment-button ${
                activeSegment === "few-shots"
                  ? "bg-blue-500 text-white"
                  : "bg-white text-gray-700 hover:bg-gray-50"
              }`}
              style={{ fontSize: "14px" }}
              type="button"
            >
              {t("systemPrompt.card.fewShots.title")}
              {isGeneratingAgent && activeSegment === "few-shots" && (
                <LoadingOutlined className="ml-2 text-white" />
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Content area - flexible height */}
      <div className="flex-1 bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden w-full max-w-4xl mx-auto min-h-0 relative">
        {/* Floating expand buttons - positioned outside scrollable content */}
        {(activeSegment === "duty" ||
          activeSegment === "constraint" ||
          activeSegment === "few-shots") && (
          <Button
            onClick={() => {
              if (activeSegment === "duty") onExpandCard?.(2);
              else if (activeSegment === "constraint") onExpandCard?.(3);
              else if (activeSegment === "few-shots") onExpandCard?.(4);
            }}
            className="absolute top-2 right-4 z-20"
            style={{
              borderRadius: "50%",
              backgroundColor: "rgba(255, 255, 255, 0.9)",
              border: "none",
              boxShadow: "0 1px 3px rgba(0, 0, 0, 0.1)",
            }}
            title={t("systemPrompt.button.expand")}
            icon={<ExpandAltOutlined />}
            size="small"
            type="text"
          />
        )}

        <style jsx global>{`
          /* Force consistent font sizes */
          .agent-config-content * {
            font-size: inherit !important;
          }
          .agent-config-content input,
          .agent-config-content select,
          .agent-config-content textarea {
            font-size: 14px !important;
          }
          .agent-config-content label {
            font-size: 14px !important;
          }
          /* Prevent button click issues */
          .segment-button {
            user-select: none !important;
            -webkit-user-select: none !important;
            -moz-user-select: none !important;
            -ms-user-select: none !important;
          }
          .segment-button:focus {
            outline: none !important;
          }
          /* Responsive button styles */
          .responsive-button {
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
          }

          /* Ensure button container has proper spacing */
          .agent-config-buttons {
            min-height: 60px !important;
            padding: 16px 20px !important;
            box-sizing: border-box !important;
          }

          /* Responsive adjustments for button container */
          @media (max-width: 768px) {
            .agent-config-buttons {
              min-height: 50px !important;
              padding: 12px 16px !important;
            }
            .responsive-button {
              font-size: 12px !important;
              padding: 6px 12px !important;
              height: 30px !important;
            }
          }

          @media (max-width: 480px) {
            .agent-config-buttons {
              min-height: 45px !important;
              padding: 10px 12px !important;
            }
            .responsive-button {
              font-size: 11px !important;
              padding: 4px 8px !important;
              height: 26px !important;
            }
          }

          /* Fix Ant Design button hover border color issues - ensure consistent color scheme */
          .responsive-button.ant-btn:hover {
            border-color: inherit !important;
          }

          /* Blue button: hover background blue-600, border should also be blue-600 */
          .bg-blue-500.hover\\:bg-blue-600.border-blue-500.hover\\:border-blue-600.ant-btn:hover {
            border-color: #2563eb !important; /* blue-600 */
          }

          /* Green button: hover background green-600, border should also be green-600 */
          .bg-green-500.hover\\:bg-green-600.border-green-500.hover\\:border-green-600.ant-btn:hover {
            border-color: #16a34a !important; /* green-600 */
          }

          /* Red button: hover background red-600, border should also be red-600 */
          .bg-red-500.hover\\:bg-red-600.border-red-500.hover\\:border-red-600.ant-btn:hover {
            border-color: #dc2626 !important; /* red-600 */
          }
        `}</style>

        <div className="content-scroll h-full w-full overflow-y-auto agent-config-content">
          {/* Agent Info */}
          {activeSegment === "agent-info" && <div>{renderAgentInfo()}</div>}

          {/* Duty Content */}
          {activeSegment === "duty" && (
            <div className="h-full">{renderDutyContent()}</div>
          )}

          {/* Constraint Content */}
          {activeSegment === "constraint" && (
            <div className="h-full">{renderConstraintContent()}</div>
          )}

          {/* Few Shots Content */}
          {activeSegment === "few-shots" && (
            <div className="h-full">{renderFewShotsContent()}</div>
          )}
        </div>
      </div>

      {/* Action Buttons - Fixed at bottom - Only show in editing mode */}
      {isEditingMode && (
        <div className="flex justify-center mb-4 flex-shrink-0 agent-config-buttons">
          {/* <div className="flex gap-2 lg:gap-3 flex-wrap justify-center"> */}
          <div className="flex gap-1 sm:gap-2 lg:gap-3 flex-nowrap justify-center w-full">
            {/* Debug Button - Always show in editing mode */}
            <Button
              type="primary"
              size="middle"
              icon={<BugOutlined />}
              onClick={onDebug}
              className="bg-blue-500 hover:bg-blue-600 responsive-button"
              title={t("systemPrompt.button.debug")}
            >
              {t("systemPrompt.button.debug")}
            </Button>

            {/* Export and Delete Buttons - Only show when editing existing agent */}
            {editingAgent &&
              editingAgent.id &&
              onExportAgent &&
              !isCreatingNewAgent && (
                <>
                  <Button
                    type="primary"
                    size="middle"
                    icon={<UploadOutlined />}
                    onClick={onExportAgent}
                    className="bg-green-500 hover:bg-green-600 responsive-button"
                    title={t("agent.contextMenu.export")}
                  >
                    {t("agent.contextMenu.export")}
                  </Button>

                  <Button
                    type="primary"
                    size="middle"
                    icon={<DeleteOutlined />}
                    onClick={handleDeleteClick}
                    className="bg-red-500 hover:bg-red-600 responsive-button"
                    title={t("agent.contextMenu.delete")}
                  >
                    {t("agent.contextMenu.delete")}
                  </Button>
                </>
              )}

            {/* Save Button - Different logic for new agent vs existing agent */}
            {isCreatingNewAgent ? (
              <Button
                type="primary"
                size="middle"
                icon={<SaveOutlined />}
                onClick={onSaveAgent}
                disabled={!canActuallySave}
                className="bg-green-500 hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed responsive-button"
                title={(() => {
                  if (agentNameError) {
                    return agentNameError;
                  }
                  if (agentNameStatus === NAME_CHECK_STATUS.EXISTS_IN_TENANT) {
                    return t("agent.error.nameExists", { name: agentName });
                  }
                  if (agentDisplayNameError) {
                    return agentDisplayNameError;
                  }
                  if (
                    agentDisplayNameStatus ===
                    NAME_CHECK_STATUS.EXISTS_IN_TENANT
                  ) {
                    return t("agent.error.displayNameExists", {
                      displayName: agentDisplayName,
                    });
                  }
                  if (!canSaveAgent && getButtonTitle) {
                    const tooltipText = getButtonTitle();
                    return (
                      tooltipText ||
                      t("businessLogic.config.button.saveToAgentPool")
                    );
                  }
                  return t("businessLogic.config.button.saveToAgentPool");
                })()}
              >
                {t("businessLogic.config.button.saveToAgentPool")}
              </Button>
            ) : (
              <Button
                type="primary"
                size="middle"
                icon={<SaveOutlined />}
                onClick={onSaveAgent}
                disabled={!canActuallySave}
                className="bg-green-500 hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed responsive-button"
                title={(() => {
                  if (agentNameError) {
                    return agentNameError;
                  }
                  if (agentNameStatus === NAME_CHECK_STATUS.EXISTS_IN_TENANT) {
                    return t("agent.error.nameExists", { name: agentName });
                  }
                  if (agentDisplayNameError) {
                    return agentDisplayNameError;
                  }
                  if (
                    agentDisplayNameStatus ===
                    NAME_CHECK_STATUS.EXISTS_IN_TENANT
                  ) {
                    return t("agent.error.displayNameExists", {
                      displayName: agentDisplayName,
                    });
                  }
                  if (!canSaveAgent && getButtonTitle) {
                    const tooltipText = getButtonTitle();
                    return tooltipText || t("systemPrompt.button.save");
                  }
                  return t("systemPrompt.button.save");
                })()}
              >
                {t("systemPrompt.button.save")}
              </Button>
            )}
          </div>
        </div>
      )}

      {/* Generating prompt overlay */}
      {isGeneratingAgent && (
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(255, 255, 255, 0.9)",
            backdropFilter: "blur(2px)",
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            alignItems: "center",
            zIndex: 1000,
            borderRadius: "8px",
          }}
        >
          <div style={{ textAlign: "center", color: "#1890ff" }}>
            <Spin size="large" />
            <div
              style={{
                marginTop: "16px",
                fontSize: "16px",
                fontWeight: 500,
                color: "#1890ff",
              }}
            >
              {t("agent.generating.title")}
            </div>
            <div
              style={{
                marginTop: "8px",
                fontSize: "14px",
                color: "#666",
              }}
            >
              {t("agent.generating.subtitle")}
            </div>
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      <Modal
        title={t("businessLogic.config.modal.deleteTitle")}
        open={isDeleteModalVisible}
        onOk={handleDeleteConfirm}
        onCancel={() => setIsDeleteModalVisible(false)}
        okText={t("businessLogic.config.modal.button.confirm")}
        cancelText={t("businessLogic.config.modal.button.cancel")}
        okButtonProps={{
          danger: true,
        }}
      >
        <p>
          {t("businessLogic.config.modal.deleteContent", {
            name: agentName || "Unnamed Agent",
          })}
        </p>
      </Modal>
    </div>
  );
}
