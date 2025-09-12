"use client";

import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Badge, Input, App } from "antd";
import {
  ThunderboltOutlined,
  LoadingOutlined,
  InfoCircleOutlined,
} from "@ant-design/icons";
import { MilkdownProvider, Milkdown, useEditor } from "@milkdown/react";
import { defaultValueCtx, Editor, rootCtx } from "@milkdown/kit/core";
import { commonmark } from "@milkdown/kit/preset/commonmark";
import { nord } from "@milkdown/theme-nord";
import { listener, listenerCtx } from "@milkdown/kit/plugin/listener";

import {
  SimplePromptEditorProps,
  ExpandEditModalProps,
} from "@/types/agentConfig";
import { updateAgent } from "@/services/agentConfigService";

import AgentConfigModal from "./agent/AgentConfigModal";

import "@/styles/milkdown-nord.css";
import log from "@/lib/logger";

export function SimplePromptEditor({
  value,
  onChange,
  height = "100%",
}: SimplePromptEditorProps) {
  const [internalValue, setInternalValue] = useState(value);
  const [editorKey, setEditorKey] = useState(0);
  const isInternalChange = useRef(false);

  // Update editor when external value changes
  useEffect(() => {
    if (value !== internalValue) {
      // Only force update editor when change comes from external source
      if (!isInternalChange.current) {
        setInternalValue(value);
        setEditorKey((prev) => prev + 1);
      }
    }

    // Reset the flag after each value or internalValue change if marked as internal change.
    // This ensures that the next external change can be correctly identified after internal editing.
    if (isInternalChange.current) {
      isInternalChange.current = false;
    }
  }, [value, internalValue]);

  const { get } = useEditor(
    (root) =>
      Editor.make()
        .config((ctx) => {
          ctx.set(rootCtx, root);
          ctx.set(defaultValueCtx, internalValue || "");
        })
        .config(nord)
        .use(commonmark)
        .use(listener)
        .config((ctx) => {
          const listenerManager = ctx.get(listenerCtx);
          listenerManager.markdownUpdated((ctx, markdown) => {
            isInternalChange.current = true;
            setInternalValue(markdown);
            onChange(markdown);
          });
        }),
    [editorKey]
  ); // Only recreate when editorKey changes

  return (
    <div className="milkdown-editor-container" style={{ height }}>
      <Milkdown key={editorKey} />
    </div>
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
        className="flex flex-col"
        style={{ height: `${calculateModalHeight(editContent)}vh` }}
      >
        <div className="flex-1 border border-gray-200 rounded-md overflow-y-auto">
          <SimplePromptEditor
            value={editContent}
            onChange={(newContent) => {
              setEditContent(newContent);
            }}
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
  onModelChange?: (value: string) => void;
  onMaxStepChange?: (value: number | null) => void;
  onGenerateAgent?: () => void;
  onSaveAgent?: () => void;
  onDebug?: () => void;
  onExportAgent?: () => void;
  onDeleteAgent?: () => void;
  onDeleteSuccess?: () => void;
  getButtonTitle?: () => string;

  // Agent being edited
  editingAgent?: any;
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
}: PromptManagerProps) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  // Modal states
  const [expandModalOpen, setExpandModalOpen] = useState(false);
  const [expandIndex, setExpandIndex] = useState(0);

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
        agentDisplayName
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
    <MilkdownProvider>
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
                  paddingBottom: "40px", // Reserve space for button
                }}
                autoSize={{
                  minRows: 3,
                  maxRows: 5,
                }}
                disabled={!isEditingMode}
              />
              {/* Generate button */}
              <div className="absolute bottom-2 right-2">
                <button
                  onClick={onGenerateAgent}
                  disabled={isGeneratingAgent}
                  className="px-3 py-1.5 rounded-md flex items-center justify-center text-sm bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{ border: "none" }}
                >
                  {isGeneratingAgent ? (
                    <>
                      <LoadingOutlined spin className="mr-1" />
                      {t("businessLogic.config.button.generating")}
                    </>
                  ) : (
                    <>
                      <ThunderboltOutlined className="mr-1" />
                      {t("businessLogic.config.button.generatePrompt")}
                    </>
                  )}
                </button>
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
    </MilkdownProvider>
  );
}
