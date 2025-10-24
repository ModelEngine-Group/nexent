import React, {
  useState,
  useRef,
  forwardRef,
  useImperativeHandle,
  useEffect,
} from "react";
import { useTranslation } from "react-i18next";

import { Input, Button, App, Select } from "antd";
import { InfoCircleFilled } from "@ant-design/icons";
import { MarkdownRenderer } from "@/components/ui/markdownRenderer";

import {
  UI_CONFIG,
  COLUMN_WIDTHS,
  DOCUMENT_NAME_CONFIG,
  LAYOUT,
  DOCUMENT_STATUS,
} from "@/const/knowledgeBase";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { modelService } from "@/services/modelService";
import { Document } from "@/types/knowledgeBase";
import { ModelOption } from "@/types/modelConfig";
import { formatFileSize, sortByStatusAndDate } from "@/lib/utils";
import log from "@/lib/logger";
import { useConfig } from "@/hooks/useConfig";

import DocumentStatus from "./DocumentStatus";
import UploadArea from "../upload/UploadArea";
import { useKnowledgeBaseContext } from "../../contexts/KnowledgeBaseContext";
import { useDocumentContext } from "../../contexts/DocumentContext";

interface DocumentListProps {
  documents: Document[];
  onDelete: (id: string) => void;
  knowledgeBaseName?: string;
  modelMismatch?: boolean;
  currentModel?: string;
  knowledgeBaseModel?: string;
  embeddingModelInfo?: string;
  containerHeight?: string;
  isCreatingMode?: boolean;
  onNameChange?: (name: string) => void;
  hasDocuments?: boolean;

  // Upload related props
  isDragging?: boolean;
  onDragOver?: (e: React.DragEvent) => void;
  onDragLeave?: (e: React.DragEvent) => void;
  onDrop?: (e: React.DragEvent) => void;
  onFileSelect: (files: File[]) => void;
  onUpload?: () => void;
  isUploading?: boolean;
}

export interface DocumentListRef {
  uppy: any;
}

const DocumentListContainer = forwardRef<DocumentListRef, DocumentListProps>(
  (
    {
      documents,
      onDelete,
      knowledgeBaseName = "",
      modelMismatch = false,
      currentModel = "",
      knowledgeBaseModel = "",
      embeddingModelInfo = "",
      containerHeight = "57vh",
      isCreatingMode = false,
      onNameChange,
      hasDocuments = false,

      // Upload related props
      isDragging = false,
      onDragOver,
      onDragLeave,
      onDrop,
      onFileSelect,
      onUpload,
      isUploading = false,
    },
    ref
  ) => {
    const { message } = App.useApp();
    const uploadAreaRef = useRef<any>(null);
    const { state: docState } = useDocumentContext();
    const { modelConfig } = useConfig();

    // Use fixed height instead of percentage
    const titleBarHeight = UI_CONFIG.TITLE_BAR_HEIGHT;
    const uploadHeight = UI_CONFIG.UPLOAD_COMPONENT_HEIGHT;

    // Sort documents by status and date
    const sortedDocuments = sortByStatusAndDate(documents);

    // Get file icon
    const getFileIcon = (type: string): string => {
      switch (type.toLowerCase()) {
        case "pdf":
          return "📄";
        case "word":
          return "📝";
        case "excel":
          return "📊";
        case "powerpoint":
          return "📑";
        default:
          return "📃";
      }
    };

    // Build model mismatch info
    const getMismatchInfo = (): string => {
      if (embeddingModelInfo) return embeddingModelInfo;
      if (currentModel && knowledgeBaseModel) {
        return t("document.modelMismatch.withModels", {
          currentModel,
          knowledgeBaseModel,
        });
      }
      return t("document.modelMismatch.general");
    };

    // Expose uppy instance to parent component
    useImperativeHandle(ref, () => ({
      uppy: uploadAreaRef.current?.uppy,
    }));
    const [showDetail, setShowDetail] = React.useState(false);
    const [summary, setSummary] = useState("");
    const [isSummarizing, setIsSummarizing] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [selectedModel, setSelectedModel] = useState<number>(0);
    const [availableModels, setAvailableModels] = useState<ModelOption[]>([]);
    const [isLoadingModels, setIsLoadingModels] = useState(false);
    const {} = useKnowledgeBaseContext();
    const { t } = useTranslation();

    // Reset showDetail state when knowledge base name changes
    React.useEffect(() => {
      setShowDetail(false);
    }, [knowledgeBaseName]);

    // Load available models when showing detail
    useEffect(() => {
      const loadModels = async () => {
        if (showDetail && availableModels.length === 0) {
          setIsLoadingModels(true);
          try {
            const models = await modelService.getLLMModels();
            setAvailableModels(models);

            // Determine initial selection order:
            // 1) Knowledge base's own configured model (server-side config)
            // 2) Globally configured default LLM from quick setup (create mode or no KB model)
            // 3) First available model

            let initialModelId: number | null = null;

            // 1) Knowledge base model (if provided)
            if (knowledgeBaseModel) {
              const matchedByName = models.find((m) => m.name === knowledgeBaseModel);
              const matchedByDisplay = matchedByName
                ? null
                : models.find((m) => m.displayName === knowledgeBaseModel);
              if (matchedByName) {
                initialModelId = matchedByName.id;
              } else if (matchedByDisplay) {
                initialModelId = matchedByDisplay.id;
              }
            }

            // 2) Fallback to globally configured default LLM
            if (initialModelId === null) {
              const configuredDisplayName = modelConfig?.llm?.displayName || "";
              const configuredModelName = modelConfig?.llm?.modelName || "";

              const matchedByDisplay = models.find(
                (m) => m.displayName === configuredDisplayName && configuredDisplayName !== ""
              );
              const matchedByName = matchedByDisplay
                ? null
                : models.find(
                    (m) => m.name === configuredModelName && configuredModelName !== ""
                  );

              if (matchedByDisplay) {
                initialModelId = matchedByDisplay.id;
              } else if (matchedByName) {
                initialModelId = matchedByName.id;
              }
            }

            // 3) Final fallback to first available model
            if (initialModelId === null) {
              if (models.length > 0) {
                initialModelId = models[0].id;
              }
            }

            if (initialModelId !== null) {
              setSelectedModel(initialModelId);
            } else {
              message.warning(t("businessLogic.config.error.noAvailableModels"));
            }
          } catch (error) {
            log.error("Failed to load models:", error);
            message.error(t("modelConfig.error.loadListFailed"));
          } finally {
            setIsLoadingModels(false);
          }
        }
      };
      loadModels();
    }, [showDetail]);

    // Get summary when showing detailed content
    React.useEffect(() => {
      const fetchSummary = async () => {
        if (showDetail && knowledgeBaseName) {
          try {
            const result = await knowledgeBaseService.getSummary(
              knowledgeBaseName
            );
            setSummary(result);
          } catch (error) {
            log.error(t("knowledgeBase.error.getSummary"), error);
            message.error(t("document.summary.error"));
          }
        }
      };
      fetchSummary();
    }, [showDetail, knowledgeBaseName]);

    // Handle auto summary
    const handleAutoSummary = async () => {
      if (!knowledgeBaseName) {
        message.warning(t("document.summary.selectKnowledgeBase"));
        return;
      }

      setIsSummarizing(true);
      setSummary("");

      try {
        await knowledgeBaseService.summaryIndex(
          knowledgeBaseName,
          1000,
          (newText) => {
            setSummary((prev) => prev + newText);
          },
          selectedModel
        );
        message.success(t("document.summary.completed"));
      } catch (error) {
        message.error(t("document.summary.error"));
        log.error(t("document.summary.error"), error);
      } finally {
        setIsSummarizing(false);
      }
    };

    // Handle save summary
    const handleSaveSummary = async () => {
      if (!knowledgeBaseName) {
        message.warning(t("document.summary.selectKnowledgeBase"));
        return;
      }

      if (!summary.trim()) {
        message.warning(t("document.summary.emptyContent"));
        return;
      }

      setIsSaving(true);
      try {
        await knowledgeBaseService.changeSummary(knowledgeBaseName, summary);
        message.success(t("document.summary.saveSuccess"));
      } catch (error: any) {
        log.error(t("document.summary.saveError"), error);
        const errorMessage =
          error?.message || error?.detail || t("document.summary.saveFailed");
        message.error(errorMessage);
      } finally {
        setIsSaving(false);
        setShowDetail(false);
      }
    };

    // Refactored: Style is embedded within the component
    return (
      <div
        className={`flex flex-col w-full bg-white border border-gray-200 rounded-md shadow-sm h-full h-[${containerHeight}]`}
      >
        {/* Title bar */}
        <div
          className={`${LAYOUT.KB_HEADER_PADDING} border-b border-gray-200 flex-shrink-0 flex items-center h-[${titleBarHeight}]`}
        >
          <div className="flex items-center justify-between w-full">
            <div className="flex items-center">
              {isCreatingMode ? (
                false ? (
                  <div className="flex items-center">
                    <span className="text-blue-600 mr-2">📚</span>
                    <h3
                      className={`${LAYOUT.KB_TITLE_MARGIN} ${LAYOUT.KB_TITLE_SIZE} font-semibold text-gray-800`}
                    >
                      {knowledgeBaseName}
                    </h3>
                    {isUploading && (
                      <div className="ml-3 px-2 py-0.5 bg-blue-50 text-blue-600 text-xs font-medium rounded-md border border-blue-100">
                        {t("document.status.creating")}
                      </div>
                    )}
                  </div>
                ) : (
                  <Input
                    value={knowledgeBaseName}
                    onChange={(e) =>
                      onNameChange && onNameChange(e.target.value)
                    }
                    placeholder={t("document.input.knowledgeBaseName")}
                    className={`${LAYOUT.KB_TITLE_MARGIN} w-[320px] font-medium my-[2px]`}
                    size="large"
                    prefix={<span className="text-blue-600">📚</span>}
                    autoFocus
                    disabled={
                      hasDocuments || isUploading || docState.isLoadingDocuments
                    } // Disable editing name if there are documents or uploading
                  />
                )
              ) : (
                <h3
                  className={`${LAYOUT.KB_TITLE_MARGIN} ${LAYOUT.KB_TITLE_SIZE} font-semibold text-blue-500 flex items-center`}
                >
                  {knowledgeBaseName}
                </h3>
              )}
              {modelMismatch && !isCreatingMode && (
                <div className="ml-3 mt-0.5 px-1.5 py-1 inline-flex items-center rounded-md text-xs font-medium bg-yellow-100 text-yellow-800 border border-yellow-200">
                  {getMismatchInfo()}
                </div>
              )}
            </div>
            {/* Right: detailed content */}
            {!isCreatingMode && (
              <Button type="primary" onClick={() => setShowDetail(true)}>
                {t("document.button.details")}
              </Button>
            )}
          </div>
        </div>

        {/* Document list */}
        <div
          className="p-2 overflow-auto flex-grow"
          onDragOver={(e) => {
            if (!isCreatingMode && knowledgeBaseName) {
              return;
            }
            e.preventDefault();
            e.stopPropagation();
          }}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
          onDragEnter={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
          onDragLeave={(e) => {
            e.preventDefault();
            e.stopPropagation();
          }}
        >
          {showDetail ? (
            <div className="px-8 py-4 h-full flex flex-col">
              <div className="flex items-center justify-between mb-5">
                <span className="font-bold text-lg">
                  {t("document.summary.title")}
                </span>
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-gray-600">
                      {t("document.summary.modelLabel")}:
                    </span>
                    <Select
                      value={selectedModel}
                      onChange={setSelectedModel}
                      loading={isLoadingModels}
                      disabled={isSummarizing}
                      style={{ width: 200 }}
                      placeholder={t("document.summary.modelPlaceholder")}
                      options={availableModels.map((model) => ({
                        value: model.id,
                        label: model.displayName,
                        disabled: model.connect_status === "unavailable",
                      }))}
                    />
                  </div>
                  <Button
                    type="default"
                    onClick={handleAutoSummary}
                    loading={isSummarizing}
                    disabled={
                      !knowledgeBaseName || isSummarizing || !selectedModel
                    }
                  >
                    {t("document.button.autoSummary")}
                  </Button>
                </div>
              </div>
              <div className="flex-1 min-h-0 mb-5 border border-gray-300 rounded-md overflow-auto">
                <div className="p-5 text-lg leading-[1.7] whitespace-pre-wrap">
                  <MarkdownRenderer content={summary} />
                </div>
              </div>
              <div className="flex gap-3 justify-end">
                <Button
                  type="primary"
                  size="large"
                  onClick={handleSaveSummary}
                  loading={isSaving}
                  disabled={!summary || isSaving}
                >
                  {t("common.save")}
                </Button>
                <Button size="large" onClick={() => setShowDetail(false)}>
                  {t("common.back")}
                </Button>
              </div>
            </div>
          ) : docState.isLoadingDocuments ? (
            <div className="flex items-center justify-center h-full border border-gray-200 rounded-md">
              <div className="text-center">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-2"></div>
                <p className="text-sm text-gray-600">
                  {t("document.status.loadingList")}
                </p>
              </div>
            </div>
          ) : isCreatingMode ? (
            <div className="flex items-center justify-center border border-gray-200 rounded-md h-full">
              <div className="text-center p-6">
                <div className="mb-4 text-blue-600 text-[36px]">
                  <InfoCircleFilled />
                </div>
                <h3 className="text-lg font-medium text-gray-800 mb-2">
                  {t("document.title.createNew")}
                </h3>
                <p className="text-gray-500 text-sm max-w-md">
                  {t("document.hint.uploadToCreate")}
                </p>
              </div>
            </div>
          ) : sortedDocuments.length > 0 ? (
            <div className="overflow-y-auto border border-gray-200 rounded-md h-full">
              <table className="min-w-full bg-white">
                <thead
                  className={`${LAYOUT.TABLE_HEADER_BG} sticky top-0 z-10`}
                >
                  <tr>
                    <th
                      className={`${LAYOUT.CELL_PADDING} text-left ${LAYOUT.HEADER_TEXT} w-[${COLUMN_WIDTHS.NAME}]`}
                    >
                      {t("document.table.header.name")}
                    </th>
                    <th
                      className={`${LAYOUT.CELL_PADDING} text-left ${LAYOUT.HEADER_TEXT} w-[${COLUMN_WIDTHS.STATUS}]`}
                    >
                      {t("document.table.header.status")}
                    </th>
                    <th
                      className={`${LAYOUT.CELL_PADDING} text-left ${LAYOUT.HEADER_TEXT} w-[${COLUMN_WIDTHS.SIZE}]`}
                    >
                      {t("document.table.header.size")}
                    </th>
                    <th
                      className={`${LAYOUT.CELL_PADDING} text-left ${LAYOUT.HEADER_TEXT} w-[${COLUMN_WIDTHS.DATE}]`}
                    >
                      {t("document.table.header.date")}
                    </th>
                    <th
                      className={`${LAYOUT.CELL_PADDING} text-left ${LAYOUT.HEADER_TEXT} w-[${COLUMN_WIDTHS.ACTION}]`}
                    >
                      {t("document.table.header.action")}
                    </th>
                  </tr>
                </thead>
                <tbody className={LAYOUT.TABLE_ROW_DIVIDER}>
                  {sortedDocuments.map((doc) => (
                    <tr key={doc.id} className={LAYOUT.TABLE_ROW_HOVER}>
                      <td className={LAYOUT.CELL_PADDING}>
                        <div className="flex items-center">
                          <span
                            className={`${LAYOUT.ICON_MARGIN} ${LAYOUT.ICON_SIZE}`}
                          >
                            {getFileIcon(doc.type)}
                          </span>
                          <span
                            className={`${LAYOUT.TEXT_SIZE} font-medium text-gray-800 truncate max-w-[${DOCUMENT_NAME_CONFIG.MAX_WIDTH}] whitespace-${DOCUMENT_NAME_CONFIG.WHITE_SPACE} overflow-${DOCUMENT_NAME_CONFIG.OVERFLOW} text-${DOCUMENT_NAME_CONFIG.TEXT_OVERFLOW}`}
                            title={doc.name}
                          >
                            {doc.name}
                          </span>
                        </div>
                      </td>
                      <td className={LAYOUT.CELL_PADDING}>
                        <div className="flex items-center">
                          <DocumentStatus status={doc.status} showIcon={true} />
                        </div>
                      </td>
                      <td
                        className={`${LAYOUT.CELL_PADDING} ${LAYOUT.TEXT_SIZE} text-gray-600`}
                      >
                        {formatFileSize(doc.size)}
                      </td>
                      <td
                        className={`${LAYOUT.CELL_PADDING} ${LAYOUT.TEXT_SIZE} text-gray-600`}
                      >
                        {new Date(doc.create_time).toLocaleString()}
                      </td>
                      <td className={LAYOUT.CELL_PADDING}>
                        <button
                          onClick={() => onDelete(doc.id)}
                          className={LAYOUT.ACTION_TEXT}
                          disabled={
                            doc.status ===
                              DOCUMENT_STATUS.WAIT_FOR_PROCESSING ||
                            doc.status === DOCUMENT_STATUS.PROCESSING ||
                            doc.status ===
                              DOCUMENT_STATUS.WAIT_FOR_FORWARDING ||
                            doc.status === DOCUMENT_STATUS.FORWARDING
                          }
                        >
                          {t("common.delete")}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-2 text-gray-500 text-xs border border-gray-200 rounded-md h-full">
              {t("document.hint.noDocuments")}
            </div>
          )}
        </div>

        {/* Upload area */}
        {!showDetail && (
          <UploadArea
            key={
              isCreatingMode
                ? `create-${knowledgeBaseName}`
                : `view-${knowledgeBaseName}`
            }
            ref={uploadAreaRef}
            onFileSelect={onFileSelect}
            onUpload={onUpload || (() => {})}
            isUploading={isUploading}
            isDragging={isDragging}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
            disabled={!isCreatingMode && !knowledgeBaseName}
            componentHeight={uploadHeight}
            isCreatingMode={isCreatingMode}
            indexName={knowledgeBaseName}
            newKnowledgeBaseName={isCreatingMode ? knowledgeBaseName : ""}
            modelMismatch={modelMismatch}
          />
        )}
      </div>
    );
  }
);

export default DocumentListContainer;
