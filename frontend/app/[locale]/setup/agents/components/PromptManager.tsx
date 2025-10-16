"use client";

import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Badge, Input, App, Dropdown, Button, Select } from "antd";
import {
  ThunderboltOutlined,
  LoadingOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";

import {
  SimplePromptEditorProps,
  ExpandEditModalProps,
} from "@/types/agentConfig";
import { updateAgent } from "@/services/agentConfigService";
import { modelService } from "@/services/modelService";
import { ModelOption } from "@/types/modelConfig";
import { useConfig } from "@/hooks/useConfig";

import AgentConfigModal from "./agent/AgentConfigModal";

import log from "@/lib/logger";

export function SimplePromptEditor({
  value,
  onChange,
  height,
  bordered = false,
}: SimplePromptEditorProps) {
  const [internalValue, setInternalValue] = useState(value);
  const isInternalChange = useRef(false);

  useEffect(() => {
    if (value !== internalValue && !isInternalChange.current) {
      setInternalValue(value);
    }
    if (isInternalChange.current) {
      isInternalChange.current = false;
    }
  }, [value, internalValue]);

  return (
    <Input.TextArea
      value={internalValue}
      onChange={(e) => {
        isInternalChange.current = true;
        setInternalValue(e.target.value);
        onChange(e.target.value);
      }}
      style={
        height
          ? { height, resize: "none", overflow: "auto" }
          : { resize: "none", overflow: "hidden" }
      }
      autoSize={height ? false : { minRows: 8 }}
      bordered={bordered}
    />
  );
}

// Expand edit modal

function ExpandEditModal({
  open,
  title,
  content,
  index,
  onClose,
  onSave,
}: ExpandEditModalProps) {
  const { t } = useTranslation("common");
  const [editContent, setEditContent] = useState(content);

  // Update edit content when content or open state changes
  useEffect(() => {
    if (open) {
      // Always use the latest content when modal opens
      setEditContent(content);
    }
  }, [content, open]);

  const handleSave = () => {
    onSave(editContent);
    onClose();
  };

  const handleClose = () => {
    // Close without saving changes
    onClose();
  };

  const getBadgeProps = (index: number) => {
    switch (index) {
      case 1:
        return { status: "success" as const };
      case 2:
        return { status: "warning" as const };
      case 3:
        return { color: "#1677ff" };
      case 4:
        return { status: "default" as const };
      default:
        return { status: "default" as const };
    }
  };

  const calculateModalHeight = (content: string) => {
    const lineCount = content.split("\n").length;
    const contentLength = content.length;
    const heightByLines = 25 + Math.floor(lineCount / 8) * 5;
    const heightByContent = 25 + Math.floor(contentLength / 200) * 3;
    const calculatedHeight = Math.max(heightByLines, heightByContent);
    return Math.max(25, Math.min(85, calculatedHeight));
  };

  return (
    <Modal
      title={
        <div className="flex justify-between items-center">
          <div className="flex items-center">
            <Badge {...getBadgeProps(index)} className="mr-3" />
            <span className="text-base font-medium">{title}</span>
          </div>
          <button
            onClick={handleSave}
            className="px-4 py-1.5 rounded-md text-sm bg-blue-500 text-white hover:bg-blue-600"
            style={{ border: "none" }}
          >
            {t("systemPrompt.expandEdit.close")}
          </button>
        </div>
      }
      open={open}
      closeIcon={null}
      onCancel={handleClose}
      footer={null}
      width={1000}
      styles={{
        body: { padding: "20px" },
        content: { top: 20 },
      }}
    >
      <div
        className="flex flex-col expand-edit-gray-textarea"
        style={{ height: `${calculateModalHeight(editContent)}vh` }}
      >
        <style jsx global>{`
          .expand-edit-gray-textarea .ant-input,
          .expand-edit-gray-textarea .ant-input:hover,
          .expand-edit-gray-textarea .ant-input:focus,
          .expand-edit-gray-textarea .ant-input-focused,
          .expand-edit-gray-textarea .ant-input-textarea,
          .expand-edit-gray-textarea .ant-input-textarea:hover,
          .expand-edit-gray-textarea .ant-input-textarea:focus,
          .expand-edit-gray-textarea .ant-input-textarea:focus-within {
            border-color: #d9d9d9 !important;
            box-shadow: none !important;
          }
        `}</style>
        <div className="flex-1 min-h-0">
          <SimplePromptEditor
            value={editContent}
            onChange={(newContent) => {
              setEditContent(newContent);
            }}
            bordered={true}
            height={"100%"}
          />
        </div>
      </div>
    </Modal>
  );
}

// Main prompt manager component
export interface PromptManagerProps {
  // Basic data
  agentId?: number;
  businessLogic?: string;
  dutyContent?: string;
  constraintContent?: string;
  fewShotsContent?: string;

  // Agent information
  agentName?: string;
  agentDescription?: string;
  agentDisplayName?: string;
  mainAgentModel?: string;
  mainAgentModelId?: number | null;
  mainAgentMaxStep?: number;

  // Edit state
  isEditingMode?: boolean;
  isGeneratingAgent?: boolean;
  isCreatingNewAgent?: boolean;
  canSaveAgent?: boolean;

  // Callback functions
  onBusinessLogicChange?: (content: string) => void;
  onDutyContentChange?: (content: string) => void;
  onConstraintContentChange?: (content: string) => void;
  onFewShotsContentChange?: (content: string) => void;
  onAgentNameChange?: (name: string) => void;
  onAgentDescriptionChange?: (description: string) => void;
  onAgentDisplayNameChange?: (displayName: string) => void;
  onModelChange?: (value: string, modelId?: number) => void;
  onMaxStepChange?: (value: number | null) => void;
  onGenerateAgent?: (model: ModelOption) => void;
  onSaveAgent?: () => void;
  onDebug?: () => void;
  onExportAgent?: () => void;
  onDeleteAgent?: () => void;
  onDeleteSuccess?: () => void;
  getButtonTitle?: () => string;

  // Agent being edited
  editingAgent?: any;

  // Model selection callbacks
  onModelSelect?: (model: ModelOption | null) => void;
  selectedGenerateModel?: ModelOption | null;
}

export default function PromptManager({
  agentId,
  businessLogic = "",
  dutyContent = "",
  constraintContent = "",
  fewShotsContent = "",
  agentName = "",
  agentDescription = "",
  agentDisplayName = "",
  mainAgentModel = "",
  mainAgentModelId = null,
  mainAgentMaxStep = 5,
  isEditingMode = false,
  isGeneratingAgent = false,
  isCreatingNewAgent = false,
  canSaveAgent = false,
  onBusinessLogicChange,
  onDutyContentChange,
  onConstraintContentChange,
  onFewShotsContentChange,
  onAgentNameChange,
  onAgentDescriptionChange,
  onAgentDisplayNameChange,
  onModelChange,
  onMaxStepChange,
  onGenerateAgent,
  onSaveAgent,
  onDebug,
  onExportAgent,
  onDeleteAgent,
  onDeleteSuccess,
  getButtonTitle,
  editingAgent,
  onModelSelect,
}: PromptManagerProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const { modelConfig } = useConfig();

  // Modal states
  const [expandModalOpen, setExpandModalOpen] = useState(false);
  const [expandIndex, setExpandIndex] = useState(0);

  // Model selection states
  const [availableModels, setAvailableModels] = useState<ModelOption[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [showModelDropdown, setShowModelDropdown] = useState(false);
  
  // Business logic model selection state
  const [businessLogicModel, setBusinessLogicModel] = useState<string>("");
  const [businessLogicModelId, setBusinessLogicModelId] = useState<number | null>(null);

  // Load available models on component mount
  useEffect(() => {
    loadAvailableModels();
  }, []);

  // Initialize business logic model selection with user's configured model
  useEffect(() => {
    if (availableModels.length > 0 && !businessLogicModel) {
      const configuredLLMName = modelConfig.llm?.modelName;
      if (configuredLLMName) {
        // Find model by display name or model name
        const configuredModel = availableModels.find(model => 
          model.displayName === configuredLLMName || 
          model.name === configuredLLMName
        );
        if (configuredModel) {
          setBusinessLogicModel(configuredModel.displayName);
          setBusinessLogicModelId(configuredModel.id);
        }
      }
    }
  }, [availableModels, modelConfig.llm, businessLogicModel]);

  const loadAvailableModels = async () => {
    setLoadingModels(true);
    try {
      const models = await modelService.getLLMModels();
      setAvailableModels(models);
    } catch (error) {
      log.error("Failed to load available models:", error);
      message.error(t("businessLogic.config.error.loadModelsFailed"));
    } finally {
      setLoadingModels(false);
    }
  };

  // Handle model selection and auto-generate
  const handleModelSelect = (model: ModelOption) => {
    onModelSelect?.(model);
    setShowModelDropdown(false);

    // Auto-trigger generation after model selection
    if (onGenerateAgent) {
      onGenerateAgent(model);
    }
  };

  // Handle business logic model selection
  const handleBusinessLogicModelChange = (value: string, option: any) => {
    const modelId = option && 'key' in option ? Number(option.key) : undefined;
    setBusinessLogicModel(value);
    setBusinessLogicModelId(modelId || null);
  };

  // Handle generate button click - show model dropdown
  const handleGenerateClick = () => {
    if (availableModels.length === 0) {
      message.warning(t("businessLogic.config.error.noAvailableModels"));
      return;
    }

    setShowModelDropdown(true);
  };

  // Create dropdown items with disabled state for unavailable models
  const modelDropdownItems = availableModels.map((model) => {
    const isAvailable = model.connect_status === 'available';
    return {
      key: model.id,
      label: model.displayName || model.name,
      disabled: !isAvailable,
      onClick: () => handleModelSelect(model),
    };
  });

  // Handle expand edit
  const handleExpandCard = (index: number) => {
    setExpandIndex(index);
    setExpandModalOpen(true);
  };

  // Handle expand edit save
  const handleExpandSave = (newContent: string) => {
    switch (expandIndex) {
      case 2:
        onDutyContentChange?.(newContent);
        break;
      case 3:
        onConstraintContentChange?.(newContent);
        break;
      case 4:
        onFewShotsContentChange?.(newContent);
        break;
    }
  };

  // Handle manual save
  const handleSavePrompt = async () => {
    if (!agentId) return;

    try {
      const result = await updateAgent(
        Number(agentId),
        agentName,
        agentDescription,
        mainAgentModel,
        mainAgentMaxStep,
        false,
        undefined,
        businessLogic,
        dutyContent,
        constraintContent,
        fewShotsContent,
        agentDisplayName,
        mainAgentModelId ?? undefined
      );

      if (result.success) {
        onDutyContentChange?.(dutyContent);
        onConstraintContentChange?.(constraintContent);
        onFewShotsContentChange?.(fewShotsContent);
        onAgentDisplayNameChange?.(agentDisplayName);
        message.success(t("systemPrompt.message.save.success"));
      } else {
        throw new Error(result.message);
      }
    } catch (error) {
      log.error(t("systemPrompt.message.save.error"), error);
      message.error(t("systemPrompt.message.save.error"));
    }
  };

  return (
    <div className="flex flex-col h-full relative">
      <style jsx global>{`
        @media (max-width: 768px) {
          .system-prompt-container {
            overflow-y: auto !important;
            max-height: none !important;
          }
          .system-prompt-content {
            min-height: auto !important;
            max-height: none !important;
          }
        }
        @media (max-width: 1024px) {
          .system-prompt-business-logic {
            min-height: 100px !important;
            max-height: 150px !important;
          }
        }
      `}</style>

      {/* Non-editing mode overlay */}
      {!isEditingMode && (
        <div className="absolute inset-0 bg-white bg-opacity-95 flex items-center justify-center z-50 transition-all duration-300 ease-out animate-in fade-in-0">
          <div className="text-center space-y-4 animate-in fade-in-50 duration-400 delay-50">
            <InfoCircleOutlined className="text-6xl text-gray-400 transition-all duration-300 animate-in zoom-in-75 delay-100" />
            <div className="animate-in slide-in-from-bottom-2 duration-300 delay-150">
              <h3 className="text-lg font-medium text-gray-700 mb-2 transition-all duration-300">
                {t("systemPrompt.nonEditing.title")}
              </h3>
              <p className="text-sm text-gray-500 transition-all duration-300">
                {t("systemPrompt.nonEditing.subtitle")}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Main title */}
      <div className="flex justify-between items-center mb-2">
        <div className="flex items-center">
          <div className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-500 text-white text-sm font-medium mr-2">
            3
          </div>
          <h2 className="text-lg font-medium">
            {t("guide.steps.describeBusinessLogic.title")}
          </h2>
        </div>
      </div>

        {/* Main content */}
        <div className="flex-1 flex flex-col border-t pt-2 system-prompt-container overflow-hidden">
          {/* Business logic description section */}
          <div className="flex-shrink-0 mb-4">
            <div className="mb-2">
              <h3 className="text-sm font-medium text-gray-700 mb-2">
                {t("businessLogic.title")}
              </h3>
            </div>
            <div className="relative">
              <Input.TextArea
                value={businessLogic}
                onChange={(e) => onBusinessLogicChange?.(e.target.value)}
                placeholder={t("businessLogic.placeholder")}
                className="w-full resize-none p-3 text-sm transition-all duration-300 system-prompt-business-logic"
                style={{
                  minHeight: "120px",
                  maxHeight: "200px",
                  paddingRight: "12px",
                  paddingBottom: "40px", // Reserve space for controls
                }}
                autoSize={{
                  minRows: 3,
                  maxRows: 5,
                }}
                disabled={!isEditingMode}
              />
              {/* Model selection and Generate button */}
              <div className="absolute bottom-2 right-2 flex items-center gap-2">
                {/* Model selection dropdown */}
                <div className="flex items-center gap-1">
                  <span className="text-xs text-gray-600 whitespace-nowrap">
                    {t("businessLogic.config.model")}:
                  </span>
                  <Select
                    value={businessLogicModel || undefined}
                    onChange={handleBusinessLogicModelChange}
                    size="small"
                    disabled={!isEditingMode}
                    style={{ minWidth: "120px" }}
                    placeholder={t("businessLogic.config.modelPlaceholder")}
                  >
                    {availableModels.map((model) => (
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
                </div>
                
                {/* Generate button */}
                {isGeneratingAgent ? (
                  <button
                    disabled={true}
                    className="px-3 py-1.5 rounded-md flex items-center justify-center text-sm bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{ border: "none" }}
                  >
                    <LoadingOutlined spin className="mr-1" />
                    {t("businessLogic.config.button.generating")}
                  </button>
                ) : (
                  <Dropdown
                    menu={{ items: modelDropdownItems }}
                    open={showModelDropdown}
                    onOpenChange={setShowModelDropdown}
                    disabled={loadingModels || availableModels.length === 0}
                    placement="bottomRight"
                    trigger={['click']}
                  >
                    <button
                      onClick={handleGenerateClick}
                      disabled={loadingModels || availableModels.length === 0}
                      className="px-3 py-1.5 rounded-md flex items-center justify-center text-sm bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
                      style={{ border: "none" }}
                    >
                      {loadingModels ? (
                        <LoadingOutlined className="mr-1" />
                      ) : (
                        <ThunderboltOutlined className="mr-1" />
                      )}
                      {t("businessLogic.config.button.generatePrompt")}
                    </button>
                  </Dropdown>
                )}
              </div>
            </div>
          </div>

        {/* Agent configuration section */}
        <div className="flex-1 min-h-0 system-prompt-content">
          <AgentConfigModal
            agentId={agentId}
            dutyContent={dutyContent}
            constraintContent={constraintContent}
            fewShotsContent={fewShotsContent}
            onDutyContentChange={onDutyContentChange}
            onConstraintContentChange={onConstraintContentChange}
            onFewShotsContentChange={onFewShotsContentChange}
            agentName={agentName}
            agentDescription={agentDescription}
            onAgentNameChange={onAgentNameChange}
            onAgentDescriptionChange={onAgentDescriptionChange}
            agentDisplayName={agentDisplayName}
            onAgentDisplayNameChange={onAgentDisplayNameChange}
            isEditingMode={isEditingMode}
            mainAgentModel={mainAgentModel}
            mainAgentModelId={mainAgentModelId}
            mainAgentMaxStep={mainAgentMaxStep}
            onModelChange={onModelChange}
            onMaxStepChange={onMaxStepChange}
            onSavePrompt={handleSavePrompt}
            onExpandCard={handleExpandCard}
            isGeneratingAgent={isGeneratingAgent}
            onDebug={onDebug}
            onExportAgent={onExportAgent}
            onDeleteAgent={onDeleteAgent}
            onDeleteSuccess={onDeleteSuccess}
            onSaveAgent={onSaveAgent}
            isCreatingNewAgent={isCreatingNewAgent}
            editingAgent={editingAgent}
            canSaveAgent={canSaveAgent}
            getButtonTitle={getButtonTitle}
          />
        </div>
      </div>

      {/* Expand edit modal */}
      <ExpandEditModal
        key={`expand-modal-${expandIndex}-${
          expandModalOpen ? "open" : "closed"
        }`}
        title={
          expandIndex === 1
            ? t("systemPrompt.expandEdit.backgroundInfo")
            : expandIndex === 2
            ? t("systemPrompt.card.duty.title")
            : expandIndex === 3
            ? t("systemPrompt.card.constraint.title")
            : t("systemPrompt.card.fewShots.title")
        }
        open={expandModalOpen}
        content={
          expandIndex === 1
            ? businessLogic
            : expandIndex === 2
            ? dutyContent
            : expandIndex === 3
            ? constraintContent
            : fewShotsContent
        }
        index={expandIndex}
        onClose={() => setExpandModalOpen(false)}
        onSave={handleExpandSave}
      />
    </div>
  );
}